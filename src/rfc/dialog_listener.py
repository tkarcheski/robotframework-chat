"""Robot Framework listener persisting dialog recordings and turns (#354).

Consumes the ``dialog_recording`` / ``dialog_turn`` /
``dialog_recording_end`` RFC_DATA events emitted by
:mod:`rfc.dialog_recorder` and ``Ask LLM``, and writes them through
:class:`rfc.harness_db.HarnessDatabase` at end-of-test. Turn numbers
are assigned in arrival order per recording and continue across tests
within a run (UNIQUE(recording_id, turn_number)).

Usage::

    robot --listener rfc.dialog_listener.DialogListener tests/
    robot --listener rfc.dialog_listener.DialogListener:database_url=<URL> tests/

Environment:
    DIALOG_DATABASE_URL  Preferred — isolates dialog rows.
    DATABASE_URL         Fallback if DIALOG_DATABASE_URL is unset.

Missing DB configuration or write failures are skip-and-log per
CLAUDE.md; the test outcome is never affected.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from .base_listener import BaseListener
from .harness_db import HarnessDatabase
from .harness_models import DialogRecording, DialogTurn

logger = logging.getLogger(__name__)

RECORDING_DATA_KEY = "dialog_recording"
TURN_DATA_KEY = "dialog_turn"
RECORDING_END_DATA_KEY = "dialog_recording_end"


class DialogListener(BaseListener):
    """Persist dialog recordings captured via RFC_DATA at end-of-test."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        super().__init__()
        self._database_url = (
            database_url
            or os.getenv("DIALOG_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        self._db: Optional[HarnessDatabase] = None
        self._turn_counters: Dict[str, int] = {}
        self._persisted_turn_count = 0

    @property
    def persisted_turn_count(self) -> int:
        return self._persisted_turn_count

    def _get_db(self) -> Optional[HarnessDatabase]:
        if self._db is not None:
            return self._db
        if not self._database_url:
            return None
        try:
            self._db = HarnessDatabase(database_url=self._database_url)
        except Exception as exc:
            logger.warning("HarnessDatabase init failed: %s", exc)
            return None
        return self._db

    def on_test_end(self, data: Any, result: Any) -> None:
        events = (
            [
                (RECORDING_DATA_KEY, p)
                for p in self.get_rfc_data_history(RECORDING_DATA_KEY)
            ]
            + [(TURN_DATA_KEY, p) for p in self.get_rfc_data_history(TURN_DATA_KEY)]
            + [
                (RECORDING_END_DATA_KEY, p)
                for p in self.get_rfc_data_history(RECORDING_END_DATA_KEY)
            ]
        )
        if not events:
            return
        db = self._get_db()
        if db is None:
            logger.info(
                "DialogListener: no DIALOG_DATABASE_URL/DATABASE_URL configured, "
                "skipping persist"
            )
            return
        for key, payload in events:
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                logger.warning("DialogListener: bad %s payload skipped: %s", key, exc)
                continue
            try:
                self._dispatch(db, key, parsed)
            except Exception as exc:  # skip-and-log: never fail the test
                logger.warning("DialogListener: %s persist failed: %s", key, exc)

    def _dispatch(self, db: HarnessDatabase, key: str, payload: Dict[str, Any]) -> None:
        if key == RECORDING_DATA_KEY:
            db.save_recording(
                DialogRecording(
                    id=str(payload["id"]),
                    source_type=str(payload.get("source_type", "live")),
                    started_at=str(payload["started_at"]),
                    session_id=str(payload.get("session_id", "")),
                    tool_name=str(payload.get("tool_name", "")),
                    tool_version=str(payload.get("tool_version", "")),
                    model_id=str(payload.get("model_id", "")),
                    metadata_json=str(payload.get("metadata_json", "")),
                )
            )
            self._turn_counters.setdefault(str(payload["id"]), 0)
        elif key == TURN_DATA_KEY:
            recording_id = str(payload["recording_id"])
            turn_number = self._turn_counters.get(recording_id, 0) + 1
            self._turn_counters[recording_id] = turn_number
            db.save_turns(
                [
                    DialogTurn(
                        recording_id=recording_id,
                        turn_number=turn_number,
                        role=str(payload["role"]),
                        timestamp=str(payload["timestamp"]),
                        content=str(payload.get("content", "")),
                        tool_calls_json=str(payload.get("tool_calls_json", "")),
                        tool_results_json=str(payload.get("tool_results_json", "")),
                        prompt_tokens=int(payload.get("prompt_tokens", -1)),
                        completion_tokens=int(payload.get("completion_tokens", -1)),
                        latency_ms=float(payload.get("latency_ms", -1.0)),
                    )
                ]
            )
            self._persisted_turn_count += 1
        elif key == RECORDING_END_DATA_KEY:
            db.end_recording(str(payload["recording_id"]), str(payload["ended_at"]))
