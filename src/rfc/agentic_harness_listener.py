"""Robot Framework listener auto-capturing per-run LLM metrics (#352).

While ``rfc harness start`` brackets a session, this listener writes
per-test EAV rows into the ``agentic_metrics`` table so dashboards can
join Robot runs to the harness row. The session_id comes from the
per-worktree sidecar (``.git/rfc-harness-session.json``), with the
``SESSION_ID`` environment variable as fallback.

Captured per test:

- ``tokens_in``     from ``RFC_DATA:llm_metrics`` ``prompt_eval_count``
- ``tokens_out``    from ``RFC_DATA:llm_metrics`` ``eval_count``
- ``latency_ms``    from ``RFC_DATA:llm_metrics`` ``total_duration_ns``
- ``grader_score``  from ``RFC_DATA:score``

No sidecar / no env var means a single warning at suite start and no
persistence; DB failures are skip-and-log per CLAUDE.md — the test
outcome is never affected.

Usage::

    robot --listener rfc.agentic_harness_listener.AgenticHarnessListener tests/

Environment:
    HARNESS_DATABASE_URL  Preferred — isolates harness/metric rows.
    DATABASE_URL          Fallback if HARNESS_DATABASE_URL is unset.
    SESSION_ID            Session fallback when no sidecar is present.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any, Optional

from .base_listener import BaseListener
from .harness_cli import active_session_id
from .harness_db import HarnessDatabase
from .harness_models import AgenticMetric
from .metrics import extract_llm_metrics

logger = logging.getLogger(__name__)

LLM_METRICS_DATA_KEY = "llm_metrics"
GRADER_SCORE_DATA_KEY = "score"


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


class AgenticHarnessListener(BaseListener):
    """Persist per-test LLM metrics to ``agentic_metrics`` at end-of-test."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        super().__init__()
        self._database_url = (
            database_url
            or os.getenv("HARNESS_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        self._db: Optional[HarnessDatabase] = None
        self._session_id = ""
        self._persisted_count = 0
        self._verified_session_id = ""
        self._session_has_harness_row = False

    @property
    def persisted_count(self) -> int:
        return self._persisted_count

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

    def on_suite_start(self, data: Any, result: Any) -> None:
        self._session_id = active_session_id() or os.getenv("SESSION_ID", "")
        if not self._session_id:
            logger.warning(
                "AgenticHarnessListener: no active harness session (sidecar "
                "or SESSION_ID); metrics will not be captured for this run."
            )

    def on_test_end(self, data: Any, result: Any) -> None:
        if not self._session_id:
            return
        metrics = self._collect_metrics()
        if not metrics:
            return
        db = self._get_db()
        if db is None:
            logger.warning(
                "AgenticHarnessListener: no HARNESS_DATABASE_URL/DATABASE_URL "
                "configured, skipping %d metric(s).",
                len(metrics),
            )
            return
        if not self._session_has_harness_row_once(db):
            return
        try:
            db.save_metrics(metrics)
            self._persisted_count += len(metrics)
        except Exception as exc:  # skip-and-log: never fail the test
            logger.warning("AgenticHarnessListener: metric persist failed: %s", exc)

    def _session_has_harness_row_once(self, db: HarnessDatabase) -> bool:
        """Verify the session has an ``agentic_harnesses`` row, once per session.

        The Makefile exports a fresh UUID as ``SESSION_ID`` when no harness
        is active, so persisting against it would violate the foreign key on
        every test (#419). Warn once and disable instead.
        """
        if self._session_id == self._verified_session_id:
            return self._session_has_harness_row
        self._verified_session_id = self._session_id
        try:
            self._session_has_harness_row = db.get_harness(self._session_id) is not None
        except Exception as exc:  # skip-and-log: never fail the test
            logger.warning("AgenticHarnessListener: harness lookup failed: %s", exc)
            self._session_has_harness_row = False
        if not self._session_has_harness_row:
            logger.warning(
                "AgenticHarnessListener: session %s has no agentic_harnesses "
                "row (run started without `rfc harness start`?); metrics "
                "will not be captured for this run.",
                self._session_id,
            )
        return self._session_has_harness_row

    def _collect_metrics(self) -> list[AgenticMetric]:
        recorded_at = _utc_now()
        rows: list[AgenticMetric] = []
        for payload in self.get_rfc_data_history(LLM_METRICS_DATA_KEY):
            parsed = extract_llm_metrics(payload)
            if not parsed:
                logger.warning(
                    "AgenticHarnessListener: bad llm_metrics payload skipped."
                )
                continue
            for metric_key, raw in (
                ("tokens_in", parsed.get("prompt_eval_count")),
                ("tokens_out", parsed.get("eval_count")),
                ("latency_ms", _ns_to_ms(parsed.get("total_duration_ns"))),
            ):
                if raw is None:
                    continue
                rows.append(
                    AgenticMetric(
                        session_id=self._session_id,
                        metric_key=metric_key,
                        recorded_at=recorded_at,
                        metric_value=float(raw),
                    )
                )
        score = self._current_test_data.get(GRADER_SCORE_DATA_KEY)
        if score is not None:
            try:
                rows.append(
                    AgenticMetric(
                        session_id=self._session_id,
                        metric_key="grader_score",
                        recorded_at=recorded_at,
                        metric_value=float(score),
                    )
                )
            except (ValueError, TypeError):
                logger.warning(
                    "AgenticHarnessListener: non-numeric score %r skipped.", score
                )
        return rows


def _ns_to_ms(value: Any) -> Optional[float]:
    """Convert a nanosecond duration to milliseconds; None passes through."""
    if value is None:
        return None
    try:
        return float(value) / 1e6
    except (ValueError, TypeError):
        return None
