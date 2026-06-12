"""Dialog Recorder — Robot keyword library for the dialog bracket (#354).

``Start Dialog Recording`` opens a recording bracket: it generates the
recording id, exposes it via the ``RFC_DIALOG_RECORDING_ID`` env flag
(read by ``Ask LLM`` to decide whether to emit ``dialog_turn`` events),
and emits a ``dialog_recording`` RFC_DATA payload for the
DialogListener to persist. ``End Dialog Recording`` closes the bracket.

If an ``rfc harness`` session is active in this worktree (sidecar at
``.git/rfc-harness-session.json``, see Issue #351), the recording is
attached to it; otherwise ``session_id`` stays empty and the recording
is written unattached.
"""

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from robot.api.deco import keyword

from .git_metadata import _git_command
from .rfc_data import emit_rfc_data

RECORDING_ENV_VAR = "RFC_DIALOG_RECORDING_ID"
_SIDECAR_NAME = "rfc-harness-session.json"


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


def _active_session_id() -> str:
    """Read the active harness session from the per-worktree sidecar."""
    git_dir = _git_command("rev-parse", "--absolute-git-dir")
    if not git_dir:
        return ""
    sidecar = Path(git_dir) / _SIDECAR_NAME
    if not sidecar.is_file():
        return ""
    try:
        return str(json.loads(sidecar.read_text()).get("session_id", ""))
    except (json.JSONDecodeError, OSError):
        return ""


class DialogRecorder:
    """Robot Framework keywords bracketing a dialog recording."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(self) -> None:
        self._recording_id: str = ""

    @keyword("Start Dialog Recording")
    def start_dialog_recording(
        self,
        source_type: str = "live",
        agent_id: str = "",
        model_id: str = "",
    ) -> str:
        """Open a recording bracket and return the new recording id."""
        recording_id = uuid.uuid4().hex
        payload = {
            "id": recording_id,
            "session_id": _active_session_id(),
            "source_type": source_type,
            "tool_name": agent_id,
            "model_id": model_id or os.environ.get("DEFAULT_MODEL", ""),
            "started_at": _utc_now(),
        }
        emit_rfc_data("dialog_recording", json.dumps(payload))
        os.environ[RECORDING_ENV_VAR] = recording_id
        self._recording_id = recording_id
        return recording_id

    @keyword("End Dialog Recording")
    def end_dialog_recording(self) -> str:
        """Close the active recording bracket and return its id."""
        recording_id = os.environ.get(RECORDING_ENV_VAR, "") or self._recording_id
        if not recording_id:
            raise RuntimeError(
                "End Dialog Recording called without an active recording "
                "(missing Start Dialog Recording bracket)."
            )
        emit_rfc_data(
            "dialog_recording_end",
            json.dumps({"recording_id": recording_id, "ended_at": _utc_now()}),
        )
        os.environ.pop(RECORDING_ENV_VAR, None)
        self._recording_id = ""
        return recording_id
