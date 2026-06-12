"""Robot Framework listener: read-only generative observation (#358).

Phase 3 of the Agentic Stack Tracker. When a suite is tagged
``generative:observe``, this listener prompts a configured LLM at hook
events (``start_suite``, and ``end_test`` when the test failed) and
records every exchange in the ``agentic_decisions`` table with full
provenance and ``applied=0`` — suggestions only, the execution
behaviour of the suite is never changed.

A hard per-suite token budget prevents recursion / runaway cost: once
``RFC_GENERATIVE_BUDGET_TOKENS`` (default 10_000) is consumed, the
listener writes ONE ``budget_exhausted`` decision and goes silent for
the rest of the suite.

All failures are skip-and-log per CLAUDE.md — the test outcome is
never affected by this listener.

Usage::

    robot --listener rfc.generative_listener.GenerativeListener tests/

Environment:
    RFC_GENERATIVE_MODEL          Prompting model (default: a fast cheap
                                  local model, ``llama3.2:1b``).
    RFC_GENERATIVE_BUDGET_TOKENS  Per-suite token budget (default 10_000).
    GENERATIVE_DATABASE_URL       Preferred DB for decision rows.
    HARNESS_DATABASE_URL          Fallback (shared with the harness tables).
    DATABASE_URL                  Final fallback.
    SESSION_ID                    Session fallback when no sidecar is present.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any, Optional

from .base_listener import BaseListener
from .harness_cli import active_session_id
from .harness_db import HarnessDatabase
from .harness_models import AgenticDecision
from .llm_client import LLMProvider, create_provider

logger = logging.getLogger(__name__)

GENERATIVE_OBSERVE_TAG = "generative:observe"
DEFAULT_GENERATIVE_MODEL = "llama3.2:1b"
DEFAULT_BUDGET_TOKENS = 10_000

_SUITE_PROMPT_TEMPLATE = (
    "You are observing a Robot Framework test run (read-only; your "
    "suggestions are recorded but never applied).\n"
    "Suite '{suite}' is starting with {test_count} test(s).\n"
    "Briefly note anything worth watching for in this suite."
)

_FAILURE_PROMPT_TEMPLATE = (
    "You are observing a Robot Framework test run (read-only; your "
    "suggestions are recorded but never applied).\n"
    "Test '{test}' in suite '{suite}' FAILED with message:\n{message}\n"
    "Captured run data: {rfc_data}\n"
    "Briefly suggest a likely cause and what a follow-up action could be."
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


def _suite_has_tag(node: Any, tag: str) -> bool:
    """Recursively check a running suite tree for a test carrying ``tag``."""
    for test in getattr(node, "tests", None) or []:
        if any(str(t).lower() == tag for t in (getattr(test, "tags", None) or [])):
            return True
    return any(
        _suite_has_tag(child, tag) for child in (getattr(node, "suites", None) or [])
    )


class GenerativeListener(BaseListener):
    """Record read-only LLM observations into ``agentic_decisions``."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        provider: Optional[LLMProvider] = None,
    ) -> None:
        super().__init__()
        self._database_url = (
            database_url
            or os.getenv("GENERATIVE_DATABASE_URL")
            or os.getenv("HARNESS_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        self._provider = provider  # injectable for tests; lazy otherwise
        self._db: Optional[HarnessDatabase] = None
        self._session_id = ""
        self._suite_name = ""
        self._observing = False
        self._budget_tokens = DEFAULT_BUDGET_TOKENS
        self._tokens_used = 0
        self._budget_exhausted = False
        self._persisted_count = 0

    @property
    def persisted_count(self) -> int:
        return self._persisted_count

    @property
    def budget_tokens(self) -> int:
        return self._budget_tokens

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        self._suite_name = getattr(data, "name", "") or ""
        self._tokens_used = 0
        self._budget_exhausted = False
        self._budget_tokens = self._read_budget()
        self._observing = _suite_has_tag(data, GENERATIVE_OBSERVE_TAG)
        if not self._observing:
            return
        self._session_id = active_session_id() or os.getenv("SESSION_ID", "")
        if not self._session_id:
            logger.warning(
                "GenerativeListener: suite %r is tagged %s but no harness "
                "session is active (sidecar or SESSION_ID); observations "
                "will not be captured.",
                self._suite_name,
                GENERATIVE_OBSERVE_TAG,
            )
            self._observing = False
            return
        if not self._session_has_harness_row():
            self._observing = False
            return
        prompt = _SUITE_PROMPT_TEMPLATE.format(
            suite=self._suite_name,
            test_count=len(getattr(data, "tests", None) or []),
        )
        self._observe("start_suite", "", prompt)

    def on_test_end(self, data: Any, result: Any) -> None:
        if not self._observing:
            return
        if getattr(result, "passed", True):
            return
        test_name = getattr(data, "name", "") or ""
        prompt = _FAILURE_PROMPT_TEMPLATE.format(
            test=test_name,
            suite=self._suite_name,
            message=getattr(result, "message", "") or "",
            rfc_data=dict(self._current_test_data) or "none",
        )
        self._observe("end_test", test_name, prompt)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_budget(self) -> int:
        raw = os.getenv("RFC_GENERATIVE_BUDGET_TOKENS", "")
        if not raw:
            return DEFAULT_BUDGET_TOKENS
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "GenerativeListener: invalid RFC_GENERATIVE_BUDGET_TOKENS=%r; "
                "using default %d.",
                raw,
                DEFAULT_BUDGET_TOKENS,
            )
            return DEFAULT_BUDGET_TOKENS

    def _get_db(self) -> Optional[HarnessDatabase]:
        if self._db is not None:
            return self._db
        if not self._database_url:
            logger.warning(
                "GenerativeListener: no GENERATIVE_DATABASE_URL/"
                "HARNESS_DATABASE_URL/DATABASE_URL configured; observations "
                "will not be captured."
            )
            return None
        try:
            self._db = HarnessDatabase(database_url=self._database_url)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: HarnessDatabase init failed: %s", exc)
            return None
        return self._db

    def _session_has_harness_row(self) -> bool:
        """The FK requires an ``agentic_harnesses`` row; warn and disable
        when the session was never started with ``rfc harness start`` (#419)."""
        db = self._get_db()
        if db is None:
            return False
        try:
            if db.get_harness(self._session_id) is not None:
                return True
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: harness lookup failed: %s", exc)
            return False
        logger.warning(
            "GenerativeListener: session %s has no agentic_harnesses row "
            "(run started without `rfc harness start`?); observations "
            "will not be captured.",
            self._session_id,
        )
        return False

    def _get_provider(self) -> Optional[LLMProvider]:
        if self._provider is not None:
            return self._provider
        model = os.getenv("RFC_GENERATIVE_MODEL", DEFAULT_GENERATIVE_MODEL)
        try:
            self._provider = create_provider(model=model)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: provider init failed: %s", exc)
            return None
        return self._provider

    def _observe(self, hook_event: str, test_name: str, prompt: str) -> None:
        """Prompt the LLM and persist the exchange, honouring the budget."""
        if self._budget_exhausted:
            return
        if self._tokens_used >= self._budget_tokens:
            self._write_budget_exhausted(hook_event, test_name)
            return
        provider = self._get_provider()
        if provider is None:
            return
        try:
            response = provider.generate(prompt)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: LLM call failed: %s", exc)
            return
        self._tokens_used += self._tokens_consumed(provider, prompt, response)
        self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event=hook_event,
                prompt_model=getattr(provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action="observe",
                applied=0,
                tokens_used=self._tokens_used,
            )
        )

    def _write_budget_exhausted(self, hook_event: str, test_name: str) -> None:
        """Record ONE budget_exhausted marker, then go silent for the suite."""
        self._budget_exhausted = True
        logger.warning(
            "GenerativeListener: token budget (%d) exhausted for suite %r "
            "after %d tokens; going silent.",
            self._budget_tokens,
            self._suite_name,
            self._tokens_used,
        )
        self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event=hook_event,
                prompt_model=os.getenv("RFC_GENERATIVE_MODEL", DEFAULT_GENERATIVE_MODEL)
                if self._provider is None
                else (getattr(self._provider, "model", "") or ""),
                prompt_text="(suppressed: token budget exhausted)",
                recorded_at=_utc_now(),
                test_name=test_name,
                proposed_action="budget_exhausted",
                applied=0,
                tokens_used=self._tokens_used,
            )
        )

    @staticmethod
    def _tokens_consumed(provider: LLMProvider, prompt: str, response: str) -> int:
        """Tokens used by the last call: provider metrics, else a rough
        4-chars-per-token estimate so the budget always drains."""
        metrics = getattr(provider, "last_metrics", None) or {}
        prompt_tokens = metrics.get("prompt_eval_count")
        completion_tokens = metrics.get("eval_count")
        if prompt_tokens is not None or completion_tokens is not None:
            return int(prompt_tokens or 0) + int(completion_tokens or 0)
        return max(1, (len(prompt) + len(response)) // 4)

    def _persist(self, decision: AgenticDecision) -> None:
        db = self._get_db()
        if db is None:
            return
        try:
            db.save_decision(decision)
            self._persisted_count += 1
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: decision persist failed: %s", exc)
