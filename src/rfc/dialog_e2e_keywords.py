"""Dialog recorder end-to-end keywords (#437).

Proves the #409 dialog recorder works end-to-end against a real database
(PostgreSQL via ``DATABASE_URL``): a child Robot run with ``DialogListener``
attached records a bracket of turns, then assertions verify the
``dialog_recordings`` / ``dialog_turns`` rows persisted intact. The database
URL travels via the ``DIALOG_DATABASE_URL`` env var because Robot's
``--listener Name:arg`` syntax splits on ``:`` and would mangle a URL.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Union

from robot.api.deco import keyword

from .dialog_recorder import RECORDING_ENV_VAR
from .harness_db import HarnessDatabase
from .rfc_data import emit_rfc_data

# Path of the inner suite the child robot process executes.
FIXTURE_SUITE = (
    Path(__file__).resolve().parents[2]
    / "robot"
    / "dialog"
    / "fixtures"
    / "record_dialog_fixture.robot"
)

# Env var telling the fixture where to write the recording id it created.
ID_FILE_ENV_VAR = "DIALOG_E2E_ID_FILE"

_LISTENER = "rfc.dialog_listener.DialogListener"
_CHILD_TIMEOUT_S = 300

# Messages DialogListener / HarnessDatabase emit on DB failure
# (skip-and-log contract — see src/rfc/dialog_listener.py).
_WARNING_MARKERS = (
    "HarnessDatabase init failed",
    "persist failed",
    "create_all() failed",
)

_VALID_ROLES = ("user", "assistant", "tool")


class DialogE2EKeywords:
    """RF keywords for end-to-end dialog recorder verification."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    @keyword("Emit Dialog Turn")
    def emit_dialog_turn(self, recording_id: str, role: str, content: str = "") -> None:
        """Emit one deterministic ``dialog_turn`` RFC_DATA event.

        Mirrors the ``Ask LLM`` recording-bracket payload without an LLM call,
        keeping the fixture suite tier:1.
        """
        if not recording_id:
            raise ValueError("recording_id must not be empty")
        if role not in _VALID_ROLES:
            raise ValueError(f"role must be one of {_VALID_ROLES}, got {role!r}")
        timestamp = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"
        emit_rfc_data(
            "dialog_turn",
            json.dumps(
                {
                    "recording_id": recording_id,
                    "role": role,
                    "content": content,
                    "timestamp": timestamp,
                }
            ),
        )

    @keyword("Run Dialog Fixture Suite")
    def run_dialog_fixture_suite(
        self, output_dir: str, database_url: str = ""
    ) -> Dict[str, Any]:
        """Run the dialog fixture suite in a child robot process.

        Attaches ``DialogListener`` via ``--listener`` so events flow through
        the real listener → HarnessDatabase → database path. Empty
        ``database_url`` leaves the listener unconfigured (no persistence).
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        id_file = out / "recording_id.txt"
        id_file.unlink(missing_ok=True)
        syslog_file = out / "robot_syslog.txt"

        env = os.environ.copy()
        env.pop(RECORDING_ENV_VAR, None)  # never inherit a stale bracket
        env[ID_FILE_ENV_VAR] = str(id_file)
        env["ROBOT_SYSLOG_FILE"] = str(syslog_file)
        if database_url:
            env["DIALOG_DATABASE_URL"] = database_url
        else:
            env.pop("DIALOG_DATABASE_URL", None)
            env.pop("DATABASE_URL", None)

        cmd = [
            sys.executable,
            "-m",
            "robot",
            "--listener",
            _LISTENER,
            "--outputdir",
            str(out),
            str(FIXTURE_SUITE),
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, timeout=_CHILD_TIMEOUT_S
        )

        recording_id = ""
        if id_file.is_file():
            recording_id = id_file.read_text(encoding="utf-8").strip()

        output_xml = out / "output.xml"
        haystacks: List[str] = [proc.stdout or "", proc.stderr or ""]
        for artifact in (output_xml, syslog_file):
            if artifact.is_file():
                haystacks.append(artifact.read_text(encoding="utf-8", errors="replace"))
        warning_found = any(
            marker in chunk for chunk in haystacks for marker in _WARNING_MARKERS
        )

        return {
            "rc": proc.returncode,
            "recording_id": recording_id,
            "output_xml": str(output_xml),
            "warning_found": warning_found,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    @keyword("Assert Dialog Recording Persisted")
    def assert_dialog_recording_persisted(
        self, database_url: str, recording_id: str, expected_turns: Union[int, str]
    ) -> Dict[str, Any]:
        """Assert the recorded dialog landed intact in the database.

        Checks one ``dialog_recordings`` row with ``ended_at`` set and exactly
        ``expected_turns`` FK-linked ``dialog_turns`` numbered 1..N.
        """
        expected = int(expected_turns)
        db = HarnessDatabase(database_url=database_url)
        recording = db.get_recording(recording_id)
        if recording is None:
            raise AssertionError(
                f"no dialog_recordings row with id={recording_id!r} in {_safe(database_url)}"
            )
        if not recording.ended_at:
            raise AssertionError(
                f"dialog_recordings.ended_at not set for id={recording_id!r} "
                "(End Dialog Recording event was not persisted)"
            )
        turns = db.get_turns(recording_id)
        if len(turns) != expected:
            raise AssertionError(
                f"expected {expected} dialog_turns rows for id={recording_id!r}, "
                f"found {len(turns)}"
            )
        numbers = [t.turn_number for t in turns]
        if numbers != list(range(1, expected + 1)):
            raise AssertionError(
                f"turn numbers not sequential 1..{expected} for id={recording_id!r}: "
                f"{numbers}"
            )
        return {
            "recording_id": recording.id,
            "ended_at": recording.ended_at,
            "turns": len(turns),
            "roles": [t.role for t in turns],
        }

    @keyword("Delete Dialog Recording")
    def delete_dialog_recording(self, database_url: str, recording_id: str) -> None:
        """Remove a recording and its turns (test cleanup, idempotent)."""
        try:
            from sqlalchemy import create_engine, text
        except ImportError as exc:  # pragma: no cover - superset extra installed in CI
            raise RuntimeError(
                "SQLAlchemy is required for Delete Dialog Recording. "
                "Install with: uv sync --extra superset"
            ) from exc
        engine = create_engine(database_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM dialog_turns WHERE recording_id = :rid"),
                    {"rid": recording_id},
                )
                conn.execute(
                    text("DELETE FROM dialog_recordings WHERE id = :rid"),
                    {"rid": recording_id},
                )
        finally:
            engine.dispose()

    @keyword("Dialog Database Reachable")
    def dialog_database_reachable(self, database_url: str) -> bool:
        """Return True if the dialog tables are reachable at the URL.

        Constructing :class:`HarnessDatabase` also runs ``create_all``, so a
        True result guarantees the dialog tables exist.
        """
        try:
            db = HarnessDatabase(database_url=database_url)
            db.get_table_row_count("dialog_recordings")
        except Exception:
            return False
        return True


def _safe(database_url: str) -> str:
    """Redact credentials from a database URL for error messages."""
    if "@" in database_url and "://" in database_url:
        scheme, rest = database_url.split("://", 1)
        return f"{scheme}://***@{rest.rsplit('@', 1)[-1]}"
    return database_url
