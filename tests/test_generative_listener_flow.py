"""Tests for rfc.generative_listener (#359) — ``generative:flow`` flow control.

Phase 3 of the Agentic Stack Tracker, first *active* generative
behavior: when a suite is tagged ``generative:flow`` the listener may
emit and apply ``proposed_action in {skip, retry, fork}`` on test
failure. Every applied action persists an ``agentic_decisions`` row
with ``applied=1``; anything that cannot be applied stays ``applied=0``.

Covers:
- retry: failed test re-run once (copy inserted after it, marker tag)
- skip: next test's body replaced with a ``Skip`` keyword carrying the
  decision id; ``applied=1``
- fork: one copy per model in ``RFC_GENERATIVE_FORK_MODELS``, tagged
  ``generative_fork:true`` and prefixed with ``Set LLM Model``
- safety rails: no fork models configured, skip with no next test,
  unparseable LLM output, retry-of-retry — all ``applied=0`` / inert
- ``generative:observe`` behaviour unchanged (read-only, ``applied=0``)
- token budget semantics identical to #358 (one ``budget_exhausted``
  marker, then silence)

All providers are synthetic — no live Ollama.
"""

from __future__ import annotations

import copy as copy_module
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from rfc.generative_listener import (
    FORK_MARKER_TAG,
    GENERATIVE_FLOW_TAG,
    GENERATIVE_OBSERVE_TAG,
    RETRY_MARKER_TAG,
    GenerativeListener,
)
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticHarness

T0 = "2026-06-12T00:00:00Z"
SESSION = "sess-gen-flow-1"

# ---------------------------------------------------------------------------
# Helpers — synthetic provider and a minimal running-model stand-in
# ---------------------------------------------------------------------------


class SyntheticProvider:
    """Stand-in LLM provider; ``responses`` are returned in order
    (last one repeats). Token drain is deterministic via metrics."""

    def __init__(
        self,
        responses: Optional[List[str]] = None,
        tokens_per_call: int = 50,
    ) -> None:
        self.model = "synthetic-test-model"
        self.last_metrics: Optional[Dict[str, Any]] = None
        self.tokens_per_call = tokens_per_call
        self.responses = responses or ["none"]
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        half = self.tokens_per_call // 2
        self.last_metrics = {
            "prompt_eval_count": half,
            "eval_count": self.tokens_per_call - half,
        }
        index = min(self.calls - 1, len(self.responses) - 1)
        return self.responses[index]


class FakeBody(list):
    """Mimics robot.running model Body: clear/create_keyword/insert/pop."""

    def create_keyword(self, name: str = "", args: Any = ()) -> SimpleNamespace:
        kw = SimpleNamespace(name=name, args=list(args))
        self.append(kw)
        return kw


class FakeTest:
    """Mimics robot.running.TestCase closely enough for the listener."""

    def __init__(self, name: str, tags: List[str], parent: Any = None) -> None:
        self.name = name
        self.tags = list(tags)
        self.body = FakeBody([SimpleNamespace(name="Original Keyword", args=[])])
        self.parent = parent
        self.setup: Any = None
        self.teardown: Any = None

    def deepcopy(self) -> "FakeTest":
        clone = FakeTest(self.name, list(self.tags), self.parent)
        clone.body = FakeBody(copy_module.deepcopy(list(self.body)))
        clone.setup = copy_module.deepcopy(self.setup)
        clone.teardown = copy_module.deepcopy(self.teardown)
        return clone


def _db_url(root) -> str:
    return f"sqlite:///{root / 'h.db'}"


def _seed_harness(root, session_id: str = SESSION) -> HarnessDatabase:
    db = HarnessDatabase(database_url=_db_url(root))
    db.save_harness(
        AgenticHarness(session_id=session_id, tool_name="claude-code", started_at=T0)
    )
    return db


def _suite(tags: List[str], test_names: List[str]) -> SimpleNamespace:
    suite = SimpleNamespace(name="Flow Suite", tests=[], suites=[])
    suite.tests = [FakeTest(n, list(tags), parent=suite) for n in test_names]
    return suite


def _run_suite(
    listener: GenerativeListener,
    suite: SimpleNamespace,
    outcomes: Dict[str, str],
    default_outcome: str = "PASS",
) -> List[FakeTest]:
    """Drive the listener through ``suite``, honouring dynamic insertion.

    ``outcomes`` maps test name -> 'PASS' | 'FAIL' | 'SKIP'; tests not in
    the map (e.g. inserted copies) get ``default_outcome``. Returns the
    tests in executed order.
    """
    executed: List[FakeTest] = []
    listener.start_suite(suite, SimpleNamespace())
    index = 0
    while index < len(suite.tests):
        test = suite.tests[index]
        listener.start_test(test, SimpleNamespace())
        # A test whose body was rewritten to a single Skip keyword is
        # skipped by Robot, not failed.
        if any(getattr(kw, "name", "") == "Skip" for kw in test.body):
            status = "SKIP"
        else:
            status = outcomes.get(test.name, default_outcome)
        result = SimpleNamespace(
            status=status,
            passed=status == "PASS",
            message="boom" if status == "FAIL" else "",
        )
        listener.end_test(test, result)
        executed.append(test)
        index += 1
    listener.end_suite(suite, SimpleNamespace())
    return executed


@pytest.fixture()
def clean_env(tmp_path, monkeypatch):
    """Isolated cwd with no session / DB / budget env leakage."""
    cwd = tmp_path / "plain"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    for var in (
        "SESSION_ID",
        "DATABASE_URL",
        "HARNESS_DATABASE_URL",
        "GENERATIVE_DATABASE_URL",
        "RFC_GENERATIVE_BUDGET_TOKENS",
        "RFC_GENERATIVE_MODEL",
        "RFC_GENERATIVE_FORK_MODELS",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SESSION_ID", SESSION)
    return cwd


def _listener(tmp_path, provider: SyntheticProvider) -> GenerativeListener:
    return GenerativeListener(database_url=_db_url(tmp_path), provider=provider)


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------


class TestFlowRetry:
    def test_retry_inserts_one_copy_and_applies(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        names = [t.name for t in executed]
        assert len(executed) == 3  # t1, retry copy, t2
        assert names[2] == "t2"
        retry_copy = executed[1]
        assert RETRY_MARKER_TAG in retry_copy.tags
        rows = db.get_decisions(SESSION, proposed_action="retry")
        assert len(rows) == 1
        assert rows[0].applied == 1
        assert rows[0].test_name == "t1"

    def test_retry_copy_failure_does_not_retry_again(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1"])
        executed = _run_suite(
            _listener(tmp_path, provider),
            suite,
            {"t1": "FAIL"},
            default_outcome="FAIL",  # the copy fails too
        )
        assert len(executed) == 2  # original + one retry, no loop
        assert provider.calls == 1  # copies never re-prompt the LLM
        assert len(db.get_decisions(SESSION, proposed_action="retry")) == 1


# ---------------------------------------------------------------------------
# skip
# ---------------------------------------------------------------------------


class TestFlowSkip:
    def test_skip_marks_next_test_skipped_with_decision_id(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["skip"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2", "t3"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 3
        rows = db.get_decisions(SESSION, proposed_action="skip")
        assert len(rows) == 1
        assert rows[0].applied == 1
        # t2's body was replaced with a single Skip keyword naming the decision
        t2 = executed[1]
        assert len(t2.body) == 1
        assert t2.body[0].name == "Skip"
        assert rows[0].id in t2.body[0].args[0]
        # t3 ran untouched
        assert executed[2].body[0].name == "Original Keyword"
        # the skipped test did not re-prompt the LLM
        assert provider.calls == 1

    def test_skip_on_last_test_is_not_applied(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["skip"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        rows = db.get_decisions(SESSION, proposed_action="skip")
        assert len(rows) == 1
        assert rows[0].applied == 0


# ---------------------------------------------------------------------------
# fork
# ---------------------------------------------------------------------------


class TestFlowFork:
    def test_fork_runs_copies_per_configured_model(
        self, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("RFC_GENERATIVE_FORK_MODELS", "modelA, modelB")
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["fork"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 5  # t1, fork x2, model restore, t2
        forks = [t for t in executed if FORK_MARKER_TAG in t.tags]
        assert len(forks) == 3  # two model forks + the restore bracket
        first = True
        for fork, model in zip(forks[:2], ["modelA", "modelB"]):
            assert f"generative_fork:model:{model}" in fork.tags
            body = list(fork.body)
            if first:
                # the pre-fork model is saved before the first switch
                assert body[0].name == "Save LLM Model"
                body = body[1:]
                first = False
            # the copy is pointed at the alternate model before anything else
            assert body[0].name == "Set LLM Model"
            assert body[0].args == [model]
            # original body preserved after the model switch
            assert body[1].name == "Original Keyword"
        assert forks[-1].body[0].name == "Restore LLM Model"
        rows = db.get_decisions(SESSION, proposed_action="fork")
        assert len(rows) == 1
        assert rows[0].applied == 1
        # fork copies never re-prompt the LLM
        assert provider.calls == 1

    def test_fork_without_configured_models_is_not_applied(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["fork"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2  # nothing inserted
        rows = db.get_decisions(SESSION, proposed_action="fork")
        assert len(rows) == 1
        assert rows[0].applied == 0


# ---------------------------------------------------------------------------
# parsing & safety rails
# ---------------------------------------------------------------------------


class TestFlowSafety:
    def test_unparseable_response_is_recorded_not_applied(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["the moon is made of cheese"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2
        rows = db.get_decisions(SESSION)
        assert len(rows) == 1
        assert rows[0].proposed_action == "none"
        assert rows[0].applied == 0

    def test_passing_tests_never_prompt(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        _run_suite(_listener(tmp_path, provider), suite, {})
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_untagged_suite_is_inert(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"])
        suite = _suite(["tier:0"], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_observe_tag_never_applies_actions(self, clean_env, tmp_path):
        """generative:observe stays read-only even if the LLM says 'retry'."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"])
        suite = _suite([GENERATIVE_OBSERVE_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2  # nothing inserted
        rows = db.get_decisions(SESSION)
        assert rows
        assert all(r.applied == 0 for r in rows)
        assert all(r.proposed_action == "observe" for r in rows)

    def test_budget_exhaustion_silences_flow_actions(
        self, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("RFC_GENERATIVE_BUDGET_TOKENS", "100")
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"], tokens_per_call=10_000)
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2", "t3", "t4"])
        _run_suite(
            _listener(tmp_path, provider),
            suite,
            {"t2": "FAIL", "t3": "FAIL", "t4": "FAIL"},
            default_outcome="FAIL",
        )
        rows = db.get_decisions(SESSION)
        exhausted = [r for r in rows if r.proposed_action == "budget_exhausted"]
        assert len(exhausted) == 1
        assert exhausted[0].applied == 0
        # only the first failure got a (budget-blowing) LLM call
        assert provider.calls == 1

    def test_no_harness_row_disables_flow(self, clean_env, tmp_path, caplog):
        db = HarnessDatabase(database_url=_db_url(tmp_path))  # no seeded row
        provider = SyntheticProvider(responses=["retry"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        with caplog.at_level("WARNING"):
            executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_flow_prompt_asks_for_an_action(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["none"])
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert provider.calls == 1
        prompt = provider.prompts[0].lower()
        for word in ("skip", "retry", "fork", "none"):
            assert word in prompt


# ---------------------------------------------------------------------------
# Codex review findings on PR #480
# ---------------------------------------------------------------------------


class TestFlowScopedToOptedInTests:
    """A flow tag in one child suite must not arm actions for siblings."""

    def test_untagged_sibling_failure_takes_no_action(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"])
        listener = _listener(tmp_path, provider)
        tagged = _suite([GENERATIVE_FLOW_TAG], ["tagged-test"])
        untagged = _suite([], ["plain-test"])
        top = SimpleNamespace(name="Top", tests=[], suites=[tagged, untagged])
        listener.start_suite(top, SimpleNamespace())
        failing = untagged.tests[0]
        before = len(untagged.tests)
        listener.end_test(
            failing,
            SimpleNamespace(status="FAIL", passed=False, message="boom"),
        )
        assert len(untagged.tests) == before, (
            "failure in an untagged sibling suite must not be retried"
        )


class TestParseActionFirstLine:
    def test_rationale_before_action_is_not_obeyed(self):
        from rfc.generative_listener import _parse_action

        assert _parse_action("Do not retry; choose none") == "none"
        assert _parse_action("I would suggest fork here") == "none"

    def test_first_line_word_with_decoration_parses(self):
        from rfc.generative_listener import _parse_action

        assert _parse_action("skip\nbecause the next test depends on this") == "skip"
        assert _parse_action("**retry**") == "retry"
        assert _parse_action("  Fork.\nrationale") == "fork"
        assert _parse_action("") == "none"


class TestPersistBeforeMutate:
    def test_no_mutation_when_decision_cannot_be_persisted(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry"])
        listener = _listener(tmp_path, provider)
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        listener.start_suite(suite, SimpleNamespace())

        class FailingDB:
            def save_decision(self, decision):
                raise RuntimeError("db down")

            def get_harness(self, session_id):
                return object()

        listener._db = FailingDB()
        before = len(suite.tests)
        listener.end_test(
            suite.tests[0],
            SimpleNamespace(status="FAIL", passed=False, message="boom"),
        )
        assert len(suite.tests) == before, (
            "run must not be mutated when the decision row cannot be persisted"
        )


class TestRetryByIdentity:
    def test_same_named_tests_each_get_their_own_retry(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["retry", "retry"])
        listener = _listener(tmp_path, provider)
        suite = _suite([GENERATIVE_FLOW_TAG], ["dup", "dup"])
        outcomes = {"dup": "FAIL"}
        executed = _run_suite(listener, suite, outcomes, default_outcome="PASS")
        copies = [t for t in executed if RETRY_MARKER_TAG in t.tags]
        assert len(copies) == 2, (
            "each same-named original test deserves its own one retry"
        )
        assert db is not None


class TestForkRestoresModel:
    def test_fork_saves_then_restores_the_original_model(
        self, clean_env, tmp_path, monkeypatch
    ):
        _seed_harness(tmp_path)
        monkeypatch.setenv("RFC_GENERATIVE_FORK_MODELS", "m1,m2")
        provider = SyntheticProvider(responses=["fork"])
        listener = _listener(tmp_path, provider)
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        outcomes = {"t1": "FAIL"}
        executed = _run_suite(listener, suite, outcomes, default_outcome="PASS")
        forks = [t for t in executed if FORK_MARKER_TAG in t.tags]
        assert len(forks) == 3, "two model forks + one restore test"
        first_fork = forks[0]
        assert getattr(first_fork.body[0], "name", "") == "Save LLM Model", (
            "the original model must be saved before the first fork switches it"
        )
        restore = forks[-1]
        assert getattr(restore.body[0], "name", "") == "Restore LLM Model", (
            "the original model must be restored after the fork copies"
        )

    def test_restore_test_drops_inherited_setup_and_teardown(
        self, clean_env, tmp_path, monkeypatch
    ):
        """The restore bracket must be unconditional: a copied setup that
        fails would prevent Restore LLM Model from ever running (model
        leak), and a copied teardown would run an extra time."""
        _seed_harness(tmp_path)
        monkeypatch.setenv("RFC_GENERATIVE_FORK_MODELS", "m1")
        provider = SyntheticProvider(responses=["fork"])
        listener = _listener(tmp_path, provider)
        suite = _suite([GENERATIVE_FLOW_TAG], ["t1", "t2"])
        suite.tests[0].setup = SimpleNamespace(name="Boot Model", args=[])
        suite.tests[0].teardown = SimpleNamespace(name="Cleanup", args=[])
        executed = _run_suite(listener, suite, {"t1": "FAIL"})
        forks = [t for t in executed if FORK_MARKER_TAG in t.tags]
        assert len(forks) == 2  # one model fork + the restore bracket
        model_fork, restore = forks
        # the model fork keeps the original fixture (it re-runs the test)
        assert model_fork.setup.name == "Boot Model"
        assert model_fork.teardown.name == "Cleanup"
        # the restore bracket runs nothing but Restore LLM Model
        assert restore.body[0].name == "Restore LLM Model"
        assert not restore.setup
        assert not restore.teardown


class TestFlowSkipScoping:
    def test_skip_does_not_cross_into_untagged_tests(self, clean_env, tmp_path):
        """A skip armed by the last flow-tagged test must not rewrite a
        following test that did not opt in (tags are per test in RF)."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["skip"])
        suite = SimpleNamespace(name="Mixed Suite", tests=[], suites=[])
        suite.tests = [
            FakeTest("t1", [GENERATIVE_FLOW_TAG], parent=suite),
            FakeTest("u1", ["tier:0"], parent=suite),
        ]
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert executed[1].body[0].name == "Original Keyword", (
            "an untagged test must never be rewritten by a flow skip"
        )
        rows = db.get_decisions(SESSION, proposed_action="skip")
        assert len(rows) == 1
        assert rows[0].applied == 0
