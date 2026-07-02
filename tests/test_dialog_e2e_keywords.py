"""Tests for rfc.dialog_e2e_keywords.DialogE2EKeywords (#437).

The keyword library drives a child Robot Framework run with
DialogListener attached and asserts the persisted dialog rows via a
database URL. These tests cover the turn emission payloads, the child
robot invocation (mocked subprocess), and the database assertion
keywords against the SQLAlchemy backend (SQLite fixture URL — the same
code path used for PostgreSQL).
"""

import importlib.util
import json
from unittest.mock import MagicMock, patch

import pytest

from rfc.dialog_e2e_keywords import DialogE2EKeywords
from rfc.dialog_recorder import RECORDING_ENV_VAR
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import DialogRecording, DialogTurn

T0 = "2026-06-12T00:00:00Z"
T1 = "2026-06-12T00:01:00Z"


@pytest.fixture()
def kw() -> DialogE2EKeywords:
    return DialogE2EKeywords()


@pytest.fixture()
def db_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'dialog_e2e.db'}"


def _seed_recording(db_url: str, recording_id: str, turns: int, ended: bool) -> None:
    db = HarnessDatabase(database_url=db_url)
    db.save_recording(
        DialogRecording(
            id=recording_id,
            source_type="live",
            started_at=T0,
            tool_name="dialog-e2e-fixture",
        )
    )
    db.save_turns(
        [
            DialogTurn(
                recording_id=recording_id,
                turn_number=n,
                role="user" if n % 2 else "assistant",
                timestamp=T0,
                content=f"turn {n}",
            )
            for n in range(1, turns + 1)
        ]
    )
    if ended:
        db.end_recording(recording_id, T1)


class TestEmitDialogTurn:
    def test_emits_dialog_turn_payload(self, kw) -> None:
        with patch("rfc.dialog_e2e_keywords.emit_rfc_data") as emit:
            kw.emit_dialog_turn("rec-1", "user", "Hello recorder")
        emit.assert_called_once()
        key, raw = emit.call_args[0]
        assert key == "dialog_turn"
        payload = json.loads(raw)
        assert payload["recording_id"] == "rec-1"
        assert payload["role"] == "user"
        assert payload["content"] == "Hello recorder"
        assert payload["timestamp"].endswith("Z")

    def test_rejects_empty_recording_id(self, kw) -> None:
        with pytest.raises(ValueError, match="recording_id"):
            kw.emit_dialog_turn("", "user", "x")

    def test_rejects_unknown_role(self, kw) -> None:
        with pytest.raises(ValueError, match="role"):
            kw.emit_dialog_turn("rec-1", "narrator", "x")


class TestRunDialogFixtureSuite:
    def _completed(self, rc: int = 0) -> MagicMock:
        proc = MagicMock()
        proc.returncode = rc
        proc.stdout = "1 test, 1 passed, 0 failed"
        proc.stderr = ""
        return proc

    def test_invokes_robot_with_dialog_listener(self, kw, tmp_path) -> None:
        out = tmp_path / "child"
        with patch(
            "rfc.dialog_e2e_keywords.subprocess.run",
            return_value=self._completed(),
        ) as run:
            result = kw.run_dialog_fixture_suite(
                str(out), database_url="postgresql://x:y@localhost:5432/rfc"
            )
        cmd = run.call_args[0][0]
        assert "--listener" in cmd
        assert "rfc.dialog_listener.DialogListener" in cmd
        assert str(out) in cmd
        assert cmd[-1].endswith("record_dialog_fixture.robot")
        assert result["rc"] == 0

    def test_database_url_passed_via_env_not_argv(self, kw, tmp_path) -> None:
        url = "postgresql://x:y@localhost:5432/rfc"
        with patch(
            "rfc.dialog_e2e_keywords.subprocess.run",
            return_value=self._completed(),
        ) as run:
            kw.run_dialog_fixture_suite(str(tmp_path / "child"), database_url=url)
        env = run.call_args[1]["env"]
        # Robot's --listener arg syntax splits on ':', which would mangle a
        # database URL — so the URL must travel via DIALOG_DATABASE_URL.
        assert env["DIALOG_DATABASE_URL"] == url
        assert all(url not in part for part in run.call_args[0][0])

    def test_clears_stale_recording_bracket_env(
        self, kw, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv(RECORDING_ENV_VAR, "stale-id")
        with patch(
            "rfc.dialog_e2e_keywords.subprocess.run",
            return_value=self._completed(),
        ) as run:
            kw.run_dialog_fixture_suite(str(tmp_path / "child"), database_url="x")
        assert RECORDING_ENV_VAR not in run.call_args[1]["env"]

    def test_reads_recording_id_written_by_fixture(self, kw, tmp_path) -> None:
        out = tmp_path / "child"

        def fake_run(cmd, **kwargs):
            id_file = kwargs["env"]["DIALOG_E2E_ID_FILE"]
            with open(id_file, "w", encoding="utf-8") as fh:
                fh.write("rec-from-fixture\n")
            return self._completed()

        with patch("rfc.dialog_e2e_keywords.subprocess.run", side_effect=fake_run):
            result = kw.run_dialog_fixture_suite(str(out), database_url="x")
        assert result["recording_id"] == "rec-from-fixture"

    def test_detects_db_failure_warning_in_child_output(self, kw, tmp_path) -> None:
        proc = self._completed()
        proc.stderr = "[ WARN ] HarnessDatabase init failed: connection refused"
        with patch("rfc.dialog_e2e_keywords.subprocess.run", return_value=proc):
            result = kw.run_dialog_fixture_suite(
                str(tmp_path / "child"),
                database_url="postgresql://bad:bad@127.0.0.1:9/x",
            )
        assert result["rc"] == 0
        assert result["warning_found"] is True

    def test_no_warning_flag_on_clean_run(self, kw, tmp_path) -> None:
        with patch(
            "rfc.dialog_e2e_keywords.subprocess.run",
            return_value=self._completed(),
        ):
            result = kw.run_dialog_fixture_suite(
                str(tmp_path / "child"), database_url="x"
            )
        assert result["warning_found"] is False


class TestAssertDialogRecordingPersisted:
    def test_passes_for_complete_recording(self, kw, db_url) -> None:
        _seed_recording(db_url, "rec-ok", turns=3, ended=True)
        summary = kw.assert_dialog_recording_persisted(db_url, "rec-ok", 3)
        assert summary["recording_id"] == "rec-ok"
        assert summary["turns"] == 3
        assert summary["ended_at"] == T1
        assert summary["roles"] == ["user", "assistant", "user"]

    def test_fails_when_recording_missing(self, kw, db_url) -> None:
        HarnessDatabase(database_url=db_url)  # create schema only
        with pytest.raises(AssertionError, match="no dialog_recordings row"):
            kw.assert_dialog_recording_persisted(db_url, "rec-missing", 3)

    def test_fails_when_ended_at_not_set(self, kw, db_url) -> None:
        _seed_recording(db_url, "rec-open", turns=2, ended=False)
        with pytest.raises(AssertionError, match="ended_at"):
            kw.assert_dialog_recording_persisted(db_url, "rec-open", 2)

    def test_fails_on_turn_count_mismatch(self, kw, db_url) -> None:
        _seed_recording(db_url, "rec-short", turns=2, ended=True)
        with pytest.raises(AssertionError, match="expected 3 dialog_turns"):
            kw.assert_dialog_recording_persisted(db_url, "rec-short", 3)

    def test_fails_on_non_sequential_turn_numbers(self, kw, db_url) -> None:
        db = HarnessDatabase(database_url=db_url)
        db.save_recording(
            DialogRecording(id="rec-gap", source_type="live", started_at=T0)
        )
        db.save_turns(
            [
                DialogTurn(
                    recording_id="rec-gap", turn_number=1, role="user", timestamp=T0
                ),
                DialogTurn(
                    recording_id="rec-gap",
                    turn_number=3,
                    role="assistant",
                    timestamp=T0,
                ),
            ]
        )
        db.end_recording("rec-gap", T1)
        with pytest.raises(AssertionError, match="turn numbers"):
            kw.assert_dialog_recording_persisted(db_url, "rec-gap", 2)

    def test_accepts_string_expected_turns_from_robot(self, kw, db_url) -> None:
        _seed_recording(db_url, "rec-str", turns=2, ended=True)
        summary = kw.assert_dialog_recording_persisted(db_url, "rec-str", "2")
        assert summary["turns"] == 2


class TestDeleteDialogRecording:
    # ``delete_dialog_recording`` requires SQLAlchemy, which ships only in the
    # ``superset`` optional-dependency extra (pyproject.toml), not the base or
    # dev install. Skip this class cleanly when it is absent rather than letting
    # the keyword raise RuntimeError at runtime (see CLAUDE.md § Rules: prefer
    # skip-and-log for optional deps; same rationale as test_answer_cache.py's
    # fakeredis importorskip). A class-scoped ``skipif`` keeps the skip narrow:
    # the other tests in this file use the stdlib sqlite path and must still run,
    # so a module-level ``importorskip`` (which would abort collection of the
    # whole file) is deliberately avoided.
    pytestmark = pytest.mark.skipif(
        importlib.util.find_spec("sqlalchemy") is None,
        reason="sqlalchemy not installed (install with: uv sync --extra superset)",
    )

    def test_removes_recording_and_turns(self, kw, db_url) -> None:
        _seed_recording(db_url, "rec-del", turns=2, ended=True)
        kw.delete_dialog_recording(db_url, "rec-del")
        db = HarnessDatabase(database_url=db_url)
        assert db.get_recording("rec-del") is None
        assert db.get_turns("rec-del") == []

    def test_noop_for_unknown_recording(self, kw, db_url) -> None:
        HarnessDatabase(database_url=db_url)  # create schema only
        kw.delete_dialog_recording(db_url, "rec-never-existed")


class TestDialogDatabaseReachable:
    def test_true_for_working_url(self, kw, db_url) -> None:
        assert kw.dialog_database_reachable(db_url) is True

    def test_false_for_unreachable_url(self, kw) -> None:
        assert (
            kw.dialog_database_reachable("postgresql://bad:bad@127.0.0.1:9/nope")
            is False
        )
