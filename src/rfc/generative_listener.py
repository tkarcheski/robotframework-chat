"""Robot Framework listener: prompt an LLM at hook events and record every
exchange in ``agentic_decisions`` (skip-and-log — listener errors never change a
test outcome). Four opt-in modes, one per suite, precedence
flow > mutate > heal > observe — observe (#358, read-only), flow (#359,
skip/retry/fork), mutate (#360, append one allow-listed assertion to a passing
test), heal (#361, run an LLM fix as a side experiment; original failure stays
official, ``applied=0`` always). ``RFC_GENERATIVE_BUDGET_TOKENS`` (default
10_000) caps per-suite spend, then writes one ``budget_exhausted`` row and goes
silent. Helpers live in :mod:`rfc.generative_listener_parsing`. Usage:
``robot --listener rfc.generative_listener.GenerativeListener tests/``
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional
from uuid import uuid4

from .base_listener import BaseListener
from .generative_listener_parsing import (
    ALLOWED_MUTATION_KEYWORDS,
    MUTATE_PROMPTS_RESOURCE as MUTATE_PROMPTS_RESOURCE,
    _add_tag,
    _assertion_like,
    _copy_test,
    _fill_template,
    _load_mutate_prompts,
    _parse_action,
    _parse_heal,
    _parse_mutation,
    _render_body,
    _suite_has_tag,
    _suite_shadows_keyword,
    _test_failed,
    _test_has_tag,
    _utc_now,
)
from .grader import Grader
from .harness_cli import active_session_id
from .harness_db import HarnessDatabase
from .harness_models import AgenticDecision, AgenticMetric
from .llm_client import LLMProvider, create_provider

logger = logging.getLogger(__name__)

GENERATIVE_OBSERVE_TAG = "generative:observe"
GENERATIVE_FLOW_TAG = "generative:flow"
GENERATIVE_MUTATE_TAG = "generative:mutate"
HEAL_SUGGEST_TAG = "heal:suggest"
RETRY_MARKER_TAG = "generative:retried"
FORK_MARKER_TAG = "generative_fork:true"
FORK_MODEL_TAG_PREFIX = "generative_fork:model:"
MUTATED_MARKER_TAG = "mutated:true"
HEALED_MARKER_TAG = "healed:true"
MUTATION_QUALITY_METRIC = "mutation_quality"
HEAL_PASSED_METRIC = "heal_passed"
# agentic_metrics.id is a PRIMARY KEY and mutation_quality already uses the bare
# decision id, so the heal-outcome metric derives its id with this suffix (chart
# join: hp.id = d.id || '-heal'). Hyphen, not colon: SQLAlchemy ``text()`` would
# read ``:heal`` in the dataset SQL as a bind parameter.
HEAL_METRIC_ID_SUFFIX = "-heal"
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


class GenerativeListener(BaseListener):
    """Record LLM observations into ``agentic_decisions``; flow mode applies
    skip / retry / fork, mutate / heal generate, run, and grade LLM-suggested
    test changes."""

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
        self._mode = ""  # "" | observe | flow | mutate | heal
        self._budget_tokens = DEFAULT_BUDGET_TOKENS
        self._tokens_used = 0
        self._budget_exhausted = False
        self._persisted_count = 0
        self._pending_skip_id = ""  # decision id to stamp on the next test
        self._retried_test_ids: set[int] = set()  # id(data): names may repeat
        self._suppressed_test_ids: set[int] = set()  # id(data) of skip targets
        self._heal_experiment_ids: dict[int, str] = {}  # id(copy) -> decision id

    @property
    def persisted_count(self) -> int:
        return self._persisted_count

    @property
    def budget_tokens(self) -> int:
        return self._budget_tokens

    @property
    def _observing(self) -> bool:
        return self._mode != ""

    # --- Hooks ---

    def on_suite_start(self, data: Any, result: Any) -> None:
        self._suite_name = getattr(data, "name", "") or ""
        self._tokens_used = 0
        self._budget_exhausted = False
        self._budget_tokens = self._read_budget()
        self._pending_skip_id = ""
        self._retried_test_ids = set()
        self._suppressed_test_ids = set()
        self._heal_experiment_ids = {}
        if _suite_has_tag(data, GENERATIVE_FLOW_TAG):
            self._mode = "flow"  # one mode per suite: flow > mutate > heal > observe
        elif _suite_has_tag(data, GENERATIVE_MUTATE_TAG):
            self._mode = "mutate"
        elif _suite_has_tag(data, HEAL_SUGGEST_TAG):
            self._mode = "heal"
        elif _suite_has_tag(data, GENERATIVE_OBSERVE_TAG):
            self._mode = "observe"
        else:
            self._mode = ""
            return
        mode_tag = {
            "flow": GENERATIVE_FLOW_TAG,
            "mutate": GENERATIVE_MUTATE_TAG,
            "heal": HEAL_SUGGEST_TAG,
            "observe": GENERATIVE_OBSERVE_TAG,
        }[self._mode]
        self._session_id = active_session_id() or os.getenv("SESSION_ID", "")
        if not self._session_id:
            logger.warning(
                "GenerativeListener: suite %r is tagged %s but no harness "
                "session is active (sidecar or SESSION_ID); observations "
                "will not be captured.",
                self._suite_name,
                mode_tag,
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
        if self._mode == "mutate":
            self._handle_mutation(data, result)
            return
        if self._mode == "heal":
            self._handle_heal(data, result)
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
        if not _test_has_tag(data, GENERATIVE_FLOW_TAG):
            return  # flow is per-test opt-in: untagged siblings stay static
        self._handle_flow_failure(data, result)

    # --- Internals ---

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
        """The FK requires an ``agentic_harnesses`` row; warn and disable when
        the session was never started with ``rfc harness start`` (#419)."""
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
        """Prompt the LLM honouring the budget; '' means no response (budget
        exhausted, provider missing, or call failed)."""
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

    # --- Flow mode (#359): skip / retry / fork ---

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
        # Audit guarantee: the decision row is persisted BEFORE the run is
        # mutated. Applicability is pre-checked so `applied` is recorded
        # truthfully; if persistence fails the mutation is withheld — active
        # flow control must never be unauditable.
        applied = 1 if self._action_applicable(action, data) else 0
        persisted = self._persist(
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
        if not persisted:
            if applied:
                logger.warning(
                    "GenerativeListener: NOT applying %r for test %r — the "
                    "decision row could not be persisted and active flow "
                    "control must stay auditable.",
                    action,
                    test_name,
                )
            return
        if not applied:
            return
        if action == "skip":
            result_applied = self._apply_skip(data, decision_id)
        elif action == "retry":
            result_applied = self._apply_retry(data, test_name)
        else:
            result_applied = self._apply_fork(data, test_name)
        if not result_applied:
            logger.warning(
                "GenerativeListener: decision %s recorded applied=1 but "
                "applying %r to test %r failed after persistence.",
                decision_id,
                action,
                test_name,
            )

    def _action_applicable(self, action: str, data: Any) -> bool:
        """Pre-check whether *action* can be applied, without mutating."""
        if action == "skip":
            tests, index = self._suite_position(data)
            if tests is None or index + 1 >= len(tests):
                return False
            # Flow is per-test opt-in: never rewrite a next test that does not
            # itself carry the flow tag (tags are per test in RF).
            if not _test_has_tag(tests[index + 1], GENERATIVE_FLOW_TAG):
                logger.warning(
                    "GenerativeListener: skip proposed after test %r but the "
                    "next test did not opt in to %s; not applied.",
                    getattr(data, "name", ""),
                    GENERATIVE_FLOW_TAG,
                )
                return False
            return True
        if action == "retry":
            if id(data) in self._retried_test_ids:
                return False
            tests, _ = self._suite_position(data)
            return tests is not None
        if action == "fork":
            if not self._fork_models():
                logger.warning(
                    "GenerativeListener: fork proposed for %r but "
                    "RFC_GENERATIVE_FORK_MODELS is not configured; not applied.",
                    getattr(data, "name", ""),
                )
                return False
            tests, _ = self._suite_position(data)
            return tests is not None
        return False

    @staticmethod
    def _fork_models() -> list[str]:
        return [
            m.strip()
            for m in os.getenv("RFC_GENERATIVE_FORK_MODELS", "").split(",")
            if m.strip()
        ]

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
        """Arm a skip for the next test; 1 if there is an opted-in next test."""
        tests, index = self._suite_position(data)
        if tests is None or index + 1 >= len(tests):
            logger.warning(
                "GenerativeListener: skip proposed after test %r but there "
                "is no next test in suite %r; not applied.",
                getattr(data, "name", ""),
                self._suite_name,
            )
            return 0
        if not _test_has_tag(tests[index + 1], GENERATIVE_FLOW_TAG):
            return 0  # per-test opt-in; pre-checked in _action_applicable
        self._pending_skip_id = decision_id
        return 1

    def _apply_retry(self, data: Any, test_name: str) -> int:
        """Insert one tagged copy of the failed test right after it."""
        if id(data) in self._retried_test_ids:
            return 0  # at most one retry per original test (by identity)
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
        self._retried_test_ids.add(id(data))
        return 1

    def _apply_fork(self, data: Any, test_name: str) -> int:
        """Insert one tagged copy per configured fork model, bracketed by
        ``Save LLM Model`` / ``Restore LLM Model`` so later original tests keep
        running against the suite's pre-fork model."""
        models = self._fork_models()
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
                if inserted == 0:
                    # Capture the pre-fork model before the first switch.
                    copy.body.create_keyword(name="Save LLM Model", args=[])
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
        if inserted:
            try:
                restore = _copy_test(data)
                restore.name = f"{test_name} (generative fork: model restore)"
                _add_tag(restore, FORK_MARKER_TAG)
                restore.body.clear()
                restore.body.create_keyword(name="Restore LLM Model", args=[])
                # The restore must be unconditional: a copied setup that fails
                # would prevent Restore LLM Model from running (model leak into
                # later tests) and a copied teardown would run an extra time
                # with an empty body.
                restore.setup = None
                restore.teardown = None
                tests.insert(index + inserted + 1, restore)
            except Exception as exc:  # skip-and-log: never fail the run
                logger.warning(
                    "GenerativeListener: could not insert model-restore test "
                    "after forking %r: %s",
                    test_name,
                    exc,
                )
        return 1 if inserted else 0

    # --- Mutate mode (#360): append one allow-listed assertion ---

    def _handle_mutation(self, data: Any, result: Any) -> None:
        """Ask the LLM for one new assertion, run it as a sibling test, and
        grade the mutation's quality in parallel."""
        status = str(getattr(result, "status", "") or "").upper()
        if status != "PASS":
            # Failed tests are not mutated: Robot stops at the first failing
            # keyword, so an assertion appended after it would never execute —
            # recording it as applied would be untrue. Skipped / not-run tests
            # have no output to mutate against.
            return
        if (
            _test_has_tag(data, MUTATED_MARKER_TAG)
            or _test_has_tag(data, RETRY_MARKER_TAG)
            or _test_has_tag(data, FORK_MARKER_TAG)
        ):
            return  # copies we inserted never trigger further mutations
        if not _test_has_tag(data, GENERATIVE_MUTATE_TAG):
            return  # mutate is per-test opt-in: untagged siblings stay static
        test_name = getattr(data, "name", "") or ""
        prompts = _load_mutate_prompts()
        prompt = _fill_template(
            prompts["MUTATION_PROMPT_TEMPLATE"],
            test=test_name,
            suite=self._suite_name,
            status=status,
            message=getattr(result, "message", "") or "none",
            rfc_data=dict(self._current_test_data) or "none",
            body=_render_body(data),
            allowed_keywords=", ".join(ALLOWED_MUTATION_KEYWORDS),
        )
        response = self._prompt_llm("end_test", test_name, prompt)
        if not response:
            return
        mutation = _parse_mutation(response)
        decision_id = uuid4().hex
        # Persist before inserting (audit guarantee, see _handle_flow_failure).
        # The failable construction (deepcopy/create_keyword) happens here,
        # pre-persist, so `applied` is truthful (#501); only the plain list
        # insert remains after the row is written.
        staged = None
        if mutation is not None and self._suite_position(data)[0] is not None:
            keyword, args = mutation
            staged = self._build_mutation_copy(data, test_name, keyword, args)
        applied = 1 if staged is not None else 0
        persisted = self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event="end_test",
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action="mutate",
                applied=applied,
                tokens_used=self._tokens_used,
                id=decision_id,
            )
        )
        if not persisted:
            if applied:
                logger.warning(
                    "GenerativeListener: NOT applying mutation for test %r — "
                    "the decision row could not be persisted and generated "
                    "tests must stay auditable.",
                    test_name,
                )
            return
        if not applied:
            if mutation is None:
                logger.warning(
                    "GenerativeListener: mutation response for %r was not a "
                    "single allow-listed assertion; recorded, not applied.",
                    test_name,
                )
            return
        keyword, args = mutation  # type: ignore[misc]
        if not self._insert_mutation_copy(data, staged):
            logger.warning(
                "GenerativeListener: decision %s recorded applied=1 but "
                "inserting the mutated copy of %r failed after persistence.",
                decision_id,
                test_name,
            )
            return
        self._grade_mutation(decision_id, test_name, status, keyword, args)

    def _build_mutation_copy(
        self, data: Any, test_name: str, keyword: str, args: list[str]
    ) -> Any | None:
        """Construct the ``<original>::mutated::<short_hash>`` sibling copy. All
        failable work happens here so callers can persist a truthful ``applied``
        before the trivial list insert (#501)."""
        if _suite_shadows_keyword(data, keyword):
            logger.warning(
                "GenerativeListener: not mutating %r — suite defines a user "
                "keyword shadowing %r; the inserted assertion could be "
                "hijacked (#516)",
                test_name,
                keyword,
            )
            return None
        assertion_line = "    ".join([keyword, *args])
        short_hash = hashlib.sha1(assertion_line.encode("utf-8")).hexdigest()[:8]
        try:
            copy = _copy_test(data)
            copy.name = f"{test_name}::mutated::{short_hash}"
            _add_tag(copy, MUTATED_MARKER_TAG)
            # Explicit BuiltIn. qualification: a user keyword of the same name
            # would shadow the BuiltIn at resolution time, so the allow-listed
            # name alone cannot guarantee which code runs (#516).
            copy.body.create_keyword(name=f"BuiltIn.{keyword}", args=list(args))
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not build mutated copy of %r: %s",
                test_name,
                exc,
            )
            return None
        return copy

    def _insert_mutation_copy(self, data: Any, copy: Any) -> int:
        """Insert a pre-built copy right after its original; it runs inline and
        gets its own ``test_runs`` row from the results listener."""
        tests, index = self._suite_position(data)
        if tests is None:
            return 0
        try:
            tests.insert(index + 1, copy)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not insert mutated copy of %r: %s",
                getattr(data, "name", ""),
                exc,
            )
            return 0
        return 1

    def _grade_mutation(
        self,
        decision_id: str,
        test_name: str,
        status: str,
        keyword: str,
        args: list[str],
    ) -> None:
        """Score the mutation quality and write ``mutation_quality`` keyed by
        the decision id. Advisory: failures never block the recorded mutation."""
        prompts = _load_mutate_prompts()
        assertion_line = "    ".join([keyword, *args])
        question = _fill_template(
            prompts["MUTATION_GRADER_QUESTION"],
            test=test_name,
            suite=self._suite_name,
            status=status,
            assertion=assertion_line,
        )
        self._grade_assertion(
            decision_id,
            test_name,
            question,
            prompts["MUTATION_GRADER_EXPECTED"],
            assertion_line,
        )

    def _grade_assertion(
        self,
        decision_id: str,
        test_name: str,
        question: str,
        expected: str,
        assertion_line: str,
    ) -> None:
        """Shared grading core for mutate and heal: score one proposed assertion
        and write ``mutation_quality`` keyed by the decision id."""
        if self._budget_exhausted:
            return
        if self._tokens_used >= self._budget_tokens:
            self._write_budget_exhausted("end_test", test_name)
            return
        provider = self._get_provider()
        if provider is None:
            return
        grade = None
        try:
            grade = Grader(provider).grade(question, expected, assertion_line)
        except Exception as exc:  # skip-and-log: grading is advisory
            logger.warning(
                "GenerativeListener: mutation_quality grading failed for "
                "decision %s: %s",
                decision_id,
                exc,
            )
        self._tokens_used += self._tokens_consumed(
            provider,
            question + expected + assertion_line,
            grade.reason if grade else "",
        )
        if grade is None:
            return
        db = self._get_db()
        if db is None:
            return
        try:
            db.save_metric(
                AgenticMetric(
                    session_id=self._session_id,
                    metric_key=MUTATION_QUALITY_METRIC,
                    metric_value=grade.score,
                    recorded_at=_utc_now(),
                    id=decision_id,
                )
            )
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not persist mutation_quality for "
                "decision %s: %s",
                decision_id,
                exc,
            )

    # --- Heal mode (#361): side-experiment fix, applied=0 always ---

    def _handle_heal(self, data: Any, result: Any) -> None:
        """On an opted-in failure, record an LLM-proposed fix (``applied=0``
        ALWAYS — the original failure stays the official outcome) and run it as
        a side-experiment sibling test."""
        experiment_decision_id = self._heal_experiment_ids.pop(id(data), "")
        if experiment_decision_id:
            self._record_heal_outcome(experiment_decision_id, data, result)
            return
        if not _test_failed(result):
            return
        if (
            _test_has_tag(data, HEALED_MARKER_TAG)
            or _test_has_tag(data, MUTATED_MARKER_TAG)
            or _test_has_tag(data, RETRY_MARKER_TAG)
            or _test_has_tag(data, FORK_MARKER_TAG)
        ):
            return  # copies we (or other modes) inserted never re-heal
        if not _test_has_tag(data, HEAL_SUGGEST_TAG):
            return  # heal is per-test opt-in: untagged siblings stay static
        test_name = getattr(data, "name", "") or ""
        prompts = _load_mutate_prompts()
        prompt = _fill_template(
            prompts["HEAL_PROMPT_TEMPLATE"],
            test=test_name,
            suite=self._suite_name,
            message=getattr(result, "message", "") or "none",
            rfc_data=dict(self._current_test_data) or "none",
            body=_render_body(data, numbered=True),
            allowed_keywords=", ".join(ALLOWED_MUTATION_KEYWORDS),
        )
        response = self._prompt_llm("end_test", test_name, prompt)
        if not response:
            return
        heal = _parse_heal(response)
        decision_id = uuid4().hex
        # Persist before inserting (audit guarantee, see _handle_flow_failure);
        # failable construction happens pre-persist. `applied` stays 0 either
        # way: a heal never changes the official outcome — heal_passed (written
        # when the experiment finishes) is the signal that the experiment ran.
        staged = None
        body = list(getattr(data, "body", None) or [])
        body_len = len(body)
        if heal is not None and self._suite_position(data)[0] is not None:
            line_number, keyword, args = heal
            if not 1 <= line_number <= body_len:
                logger.warning(
                    "GenerativeListener: heal for %r targeted body line %d "
                    "of %d; recorded, not run.",
                    test_name,
                    line_number,
                    body_len,
                )
            elif not _assertion_like(body[line_number - 1]):
                # Replacing the ACTION that caused the failure with an assertion
                # would make the experiment trivially green and surface a false
                # healing candidate (#518). Only assertion lines are eligible.
                logger.warning(
                    "GenerativeListener: heal for %r targeted body line %d "
                    "(%r), which is not an assertion; recorded, not run.",
                    test_name,
                    line_number,
                    getattr(body[line_number - 1], "name", ""),
                )
            else:
                staged = self._build_heal_copy(
                    data, test_name, line_number, keyword, args
                )
        persisted = self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event="end_test",
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action="heal",
                applied=0,  # ALWAYS: suggestion-only, no silent green-washing
                tokens_used=self._tokens_used,
                id=decision_id,
            )
        )
        if not persisted:
            if staged is not None:
                logger.warning(
                    "GenerativeListener: NOT running heal experiment for "
                    "test %r — the decision row could not be persisted and "
                    "heal experiments must stay auditable.",
                    test_name,
                )
            return
        if staged is None:
            if heal is None:
                logger.warning(
                    "GenerativeListener: heal response for %r was not a line "
                    "number plus one allow-listed assertion; recorded, not run.",
                    test_name,
                )
            return
        if not self._insert_mutation_copy(data, staged):
            return
        self._heal_experiment_ids[id(staged)] = decision_id
        line_number, keyword, args = heal  # type: ignore[misc]
        question = _fill_template(
            prompts["HEAL_GRADER_QUESTION"],
            test=test_name,
            suite=self._suite_name,
            message=getattr(result, "message", "") or "none",
            assertion="    ".join([keyword, *args]),
        )
        self._grade_assertion(
            decision_id,
            test_name,
            question,
            prompts["HEAL_GRADER_EXPECTED"],
            "    ".join([keyword, *args]),
        )

    def _build_heal_copy(
        self,
        data: Any,
        test_name: str,
        line_number: int,
        keyword: str,
        args: list[str],
    ) -> Any | None:
        """Construct the ``<original>::healed::<short_hash>`` side experiment: a
        deep copy with 1-based body line ``line_number`` replaced by the
        proposed assertion."""
        assertion_line = "    ".join([keyword, *args])
        short_hash = hashlib.sha1(
            f"{line_number}:{assertion_line}".encode()
        ).hexdigest()[:8]
        try:
            copy = _copy_test(data)
            copy.name = f"{test_name}::healed::{short_hash}"
            _add_tag(copy, HEALED_MARKER_TAG)
            copy.body.create_keyword(name=keyword, args=list(args))
            replacement = copy.body.pop()
            copy.body[line_number - 1] = replacement
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not build heal experiment for %r: %s",
                test_name,
                exc,
            )
            return None
        return copy

    def _record_heal_outcome(self, decision_id: str, data: Any, result: Any) -> None:
        """Write the side experiment's outcome to ``agentic_metrics`` as
        ``heal_passed`` (1.0/0.0) with id ``<decision_id>-heal`` — the Superset
        healing-candidates chart joins it back to the decision."""
        status = str(getattr(result, "status", "") or "").upper()
        passed = status == "PASS" if status else bool(getattr(result, "passed", False))
        db = self._get_db()
        if db is None:
            return
        try:
            db.save_metric(
                AgenticMetric(
                    session_id=self._session_id,
                    metric_key=HEAL_PASSED_METRIC,
                    metric_value=1.0 if passed else 0.0,
                    recorded_at=_utc_now(),
                    id=f"{decision_id}{HEAL_METRIC_ID_SUFFIX}",
                )
            )
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not persist heal_passed for decision %s: %s",
                decision_id,
                exc,
            )

    # --- Persist / budget ---

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

    def _persist(self, decision: AgenticDecision) -> bool:
        """Save a decision row; True on success (flow mutations gate on it)."""
        db = self._get_db()
        if db is None:
            return False
        try:
            db.save_decision(decision)
            self._persisted_count += 1
            return True
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: decision persist failed: %s", exc)
            return False
