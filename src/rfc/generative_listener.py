"""Robot Framework listener: generative observation and flow control.

Phase 3 of the Agentic Stack Tracker.

**Observe mode (#358, read-only).** When a suite is tagged
``generative:observe``, this listener prompts a configured LLM at hook
events (``start_suite``, and ``end_test`` when the test failed) and
records every exchange in the ``agentic_decisions`` table with full
provenance and ``applied=0`` — suggestions only, the execution
behaviour of the suite is never changed.

**Flow mode (#359, active, explicit opt-in).** When a suite is tagged
``generative:flow``, the listener prompts the LLM on each test failure
and may *apply* ``proposed_action in {skip, retry, fork}``:

- ``skip``  — the next test is marked SKIPPED (its body is replaced
  with a single ``Skip`` keyword naming the decision id).
- ``retry`` — the failed test is re-run once (a tagged copy is
  inserted right after it; copies are never retried again).
- ``fork``  — the failed test is re-run once per model in
  ``RFC_GENERATIVE_FORK_MODELS`` (comma-separated). Each fork copy is
  tagged ``generative_fork:true`` (so its ``test_runs`` row is
  identifiable) plus ``generative_fork:model:<model>``, and gets a
  ``Set LLM Model`` keyword prepended.

Every applied action persists a decision row with ``applied=1``;
suggestions that cannot be applied (no next test to skip, no fork
models configured, unparseable LLM output) persist with ``applied=0``.
``generative:observe`` semantics are unchanged — observe-tagged suites
never have their execution modified, whatever the LLM says. Execution
of ``generative:flow`` suites diverges from the static ``.robot`` file;
CI consumers should treat them as exploratory, not gating.

A hard per-suite token budget prevents recursion / runaway cost: once
``RFC_GENERATIVE_BUDGET_TOKENS`` (default 10_000) is consumed, the
listener writes ONE ``budget_exhausted`` decision and goes silent for
the rest of the suite (in flow mode this also stops all flow actions).

All failures are skip-and-log per CLAUDE.md — the test outcome is
never affected by listener errors.

Usage::

    robot --listener rfc.generative_listener.GenerativeListener tests/

Environment:
    RFC_GENERATIVE_MODEL          Prompting model (default: a fast cheap
                                  local model, ``llama3.2:1b``).
    RFC_GENERATIVE_BUDGET_TOKENS  Per-suite token budget (default 10_000).
    RFC_GENERATIVE_FORK_MODELS    Comma-separated model pool for ``fork``
                                  (flow mode; unset = fork never applied).
    GENERATIVE_DATABASE_URL       Preferred DB for decision rows.
    HARNESS_DATABASE_URL          Fallback (shared with the harness tables).
    DATABASE_URL                  Final fallback.
    SESSION_ID                    Session fallback when no sidecar is present.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from .base_listener import BaseListener
from .harness_cli import active_session_id
from .harness_db import HarnessDatabase
from .harness_models import AgenticDecision
from .llm_client import LLMProvider, create_provider

logger = logging.getLogger(__name__)

GENERATIVE_OBSERVE_TAG = "generative:observe"
GENERATIVE_FLOW_TAG = "generative:flow"
RETRY_MARKER_TAG = "generative:retried"
FORK_MARKER_TAG = "generative_fork:true"
FORK_MODEL_TAG_PREFIX = "generative_fork:model:"
DEFAULT_GENERATIVE_MODEL = "llama3.2:1b"
DEFAULT_BUDGET_TOKENS = 10_000

_FLOW_ACTIONS = ("skip", "retry", "fork", "none")
_ACTION_RE = re.compile(r"\b(skip|retry|fork|none)\b", re.IGNORECASE)

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

_FLOW_PROMPT_TEMPLATE = (
    "You control the flow of a Robot Framework test run (suite opted in "
    "via the generative:flow tag).\n"
    "Test '{test}' in suite '{suite}' FAILED with message:\n{message}\n"
    "Captured run data: {rfc_data}\n"
    "Reply with exactly one word on the first line — your chosen action:\n"
    "  skip  — mark the NEXT test in the suite as SKIPPED\n"
    "  retry — re-run this failed test once\n"
    "  fork  — re-run this failed test against alternate models\n"
    "  none  — take no action\n"
    "You may add a one-sentence rationale after the first line."
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


def _test_has_tag(test: Any, tag: str) -> bool:
    return any(str(t).lower() == tag for t in (getattr(test, "tags", None) or []))


def _parse_action(response: str) -> str:
    """Extract the first flow action mentioned in the LLM response.

    Anything that names none of the known actions maps to ``none``
    (recorded, never applied) — an unparseable model can never steer
    the run.
    """
    match = _ACTION_RE.search(response)
    return match.group(1).lower() if match else "none"


def _add_tag(test: Any, tag: str) -> None:
    """Add a tag on either a robot.running ``Tags`` or a plain list."""
    tags = getattr(test, "tags", None)
    if tags is None:
        return
    if hasattr(tags, "add"):
        tags.add(tag)
    else:
        tags.append(tag)


def _copy_test(test: Any) -> Any:
    """Deep-copy a running-model test (robot objects expose ``deepcopy``)."""
    if hasattr(test, "deepcopy"):
        return test.deepcopy()
    import copy as _copy

    return _copy.deepcopy(test)


def _test_failed(result: Any) -> bool:
    """True only for a genuine FAIL — SKIP must not look like a failure."""
    status = getattr(result, "status", None)
    if status is not None:
        return str(status).upper() == "FAIL"
    return not getattr(result, "passed", True)


class GenerativeListener(BaseListener):
    """Record LLM observations into ``agentic_decisions``; in flow mode
    (``generative:flow``) additionally apply skip / retry / fork."""

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
        self._mode = ""  # "" | "observe" | "flow"
        self._budget_tokens = DEFAULT_BUDGET_TOKENS
        self._tokens_used = 0
        self._budget_exhausted = False
        self._persisted_count = 0
        self._pending_skip_id = ""  # decision id to stamp on the next test
        self._retried_tests: set[str] = set()
        self._suppressed_test_ids: set[int] = set()  # id(data) of skip targets

    @property
    def persisted_count(self) -> int:
        return self._persisted_count

    @property
    def budget_tokens(self) -> int:
        return self._budget_tokens

    @property
    def _observing(self) -> bool:
        return self._mode != ""

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        self._suite_name = getattr(data, "name", "") or ""
        self._tokens_used = 0
        self._budget_exhausted = False
        self._budget_tokens = self._read_budget()
        self._pending_skip_id = ""
        self._retried_tests = set()
        self._suppressed_test_ids = set()
        if _suite_has_tag(data, GENERATIVE_FLOW_TAG):
            self._mode = "flow"
        elif _suite_has_tag(data, GENERATIVE_OBSERVE_TAG):
            self._mode = "observe"
        else:
            self._mode = ""
            return
        self._session_id = active_session_id() or os.getenv("SESSION_ID", "")
        if not self._session_id:
            logger.warning(
                "GenerativeListener: suite %r is tagged %s but no harness "
                "session is active (sidecar or SESSION_ID); observations "
                "will not be captured.",
                self._suite_name,
                GENERATIVE_FLOW_TAG if self._mode == "flow" else GENERATIVE_OBSERVE_TAG,
            )
            self._mode = ""
            return
        if not self._session_has_harness_row():
            self._mode = ""
            return
        if self._mode != "observe":
            return
        prompt = _SUITE_PROMPT_TEMPLATE.format(
            suite=self._suite_name,
            test_count=len(getattr(data, "tests", None) or []),
        )
        self._observe("start_suite", "", prompt)

    def on_test_start(self, data: Any, result: Any) -> None:
        if self._mode != "flow" or not self._pending_skip_id:
            return
        decision_id, self._pending_skip_id = self._pending_skip_id, ""
        self._suppressed_test_ids.add(id(data))
        message = f"Skipped by generative listener (decision {decision_id})"
        try:
            body = data.body
            body.clear()
            body.create_keyword(name="Skip", args=[message])
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not apply skip to test %r: %s",
                getattr(data, "name", ""),
                exc,
            )

    def on_test_end(self, data: Any, result: Any) -> None:
        if self._mode == "observe":
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
            return
        if self._mode != "flow":
            return
        if not _test_failed(result):
            return
        if id(data) in self._suppressed_test_ids:
            return  # a test we ourselves marked skipped
        if _test_has_tag(data, RETRY_MARKER_TAG) or _test_has_tag(
            data, FORK_MARKER_TAG
        ):
            return  # copies we inserted never trigger further actions
        self._handle_flow_failure(data, result)

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

    def _prompt_llm(self, hook_event: str, test_name: str, prompt: str) -> str:
        """Prompt the LLM honouring the budget; '' means no response
        (budget exhausted, provider missing, or call failed)."""
        if self._budget_exhausted:
            return ""
        if self._tokens_used >= self._budget_tokens:
            self._write_budget_exhausted(hook_event, test_name)
            return ""
        provider = self._get_provider()
        if provider is None:
            return ""
        try:
            response = provider.generate(prompt)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: LLM call failed: %s", exc)
            return ""
        self._tokens_used += self._tokens_consumed(provider, prompt, response)
        return response

    def _observe(self, hook_event: str, test_name: str, prompt: str) -> None:
        """Prompt the LLM and persist a read-only observation row."""
        response = self._prompt_llm(hook_event, test_name, prompt)
        if not response:
            return
        self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event=hook_event,
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action="observe",
                applied=0,
                tokens_used=self._tokens_used,
            )
        )

    # ------------------------------------------------------------------
    # Flow mode (#359)
    # ------------------------------------------------------------------

    def _handle_flow_failure(self, data: Any, result: Any) -> None:
        """Ask the LLM for a flow action on a failed test and apply it."""
        test_name = getattr(data, "name", "") or ""
        prompt = _FLOW_PROMPT_TEMPLATE.format(
            test=test_name,
            suite=self._suite_name,
            message=getattr(result, "message", "") or "",
            rfc_data=dict(self._current_test_data) or "none",
        )
        response = self._prompt_llm("end_test", test_name, prompt)
        if not response:
            return
        action = _parse_action(response)
        decision_id = uuid4().hex  # pre-generated so skip can stamp it
        applied = 0
        if action == "skip":
            applied = self._apply_skip(data, decision_id)
        elif action == "retry":
            applied = self._apply_retry(data, test_name)
        elif action == "fork":
            applied = self._apply_fork(data, test_name)
        self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event="end_test",
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action=action,
                applied=applied,
                tokens_used=self._tokens_used,
                id=decision_id,
            )
        )

    def _suite_position(self, data: Any) -> tuple[Any, int]:
        """Return ``(tests, index)`` for a running test, or ``(None, -1)``."""
        tests = getattr(getattr(data, "parent", None), "tests", None)
        if tests is None:
            return None, -1
        try:
            return tests, tests.index(data)
        except ValueError:
            return None, -1

    def _apply_skip(self, data: Any, decision_id: str) -> int:
        """Arm a skip for the next test; 1 if there is a next test."""
        tests, index = self._suite_position(data)
        if tests is None or index + 1 >= len(tests):
            logger.warning(
                "GenerativeListener: skip proposed after test %r but there "
                "is no next test in suite %r; not applied.",
                getattr(data, "name", ""),
                self._suite_name,
            )
            return 0
        self._pending_skip_id = decision_id
        return 1

    def _apply_retry(self, data: Any, test_name: str) -> int:
        """Insert one tagged copy of the failed test right after it."""
        if test_name in self._retried_tests:
            return 0  # at most one retry per test
        tests, index = self._suite_position(data)
        if tests is None:
            return 0
        try:
            copy = _copy_test(data)
            copy.name = f"{test_name} (generative retry)"
            _add_tag(copy, RETRY_MARKER_TAG)
            tests.insert(index + 1, copy)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not apply retry for %r: %s",
                test_name,
                exc,
            )
            return 0
        self._retried_tests.add(test_name)
        return 1

    def _apply_fork(self, data: Any, test_name: str) -> int:
        """Insert one tagged copy per configured fork model."""
        models = [
            m.strip()
            for m in os.getenv("RFC_GENERATIVE_FORK_MODELS", "").split(",")
            if m.strip()
        ]
        if not models:
            logger.warning(
                "GenerativeListener: fork proposed for %r but "
                "RFC_GENERATIVE_FORK_MODELS is not configured; not applied.",
                test_name,
            )
            return 0
        tests, index = self._suite_position(data)
        if tests is None:
            return 0
        inserted = 0
        for offset, model in enumerate(models, start=1):
            try:
                copy = _copy_test(data)
                copy.name = f"{test_name} (generative fork: {model})"
                _add_tag(copy, FORK_MARKER_TAG)
                _add_tag(copy, f"{FORK_MODEL_TAG_PREFIX}{model}")
                # Point the copy at the alternate model before anything else.
                copy.body.create_keyword(name="Set LLM Model", args=[model])
                copy.body.insert(0, copy.body.pop())
                tests.insert(index + offset, copy)
                inserted += 1
            except Exception as exc:  # skip-and-log: never fail the run
                logger.warning(
                    "GenerativeListener: could not fork %r onto model %r: %s",
                    test_name,
                    model,
                    exc,
                )
        return 1 if inserted else 0

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
