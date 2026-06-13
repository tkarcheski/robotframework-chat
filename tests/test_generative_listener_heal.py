"""Tests for rfc.generative_listener (#361) — ``heal:suggest`` self-healing.

Phase 3 of the Agentic Stack Tracker, final item: when a test tagged
``heal:suggest`` FAILS, the listener asks the LLM for a proposed fix
(one allow-listed replacement assertion for one body line), records the
suggestion in ``agentic_decisions`` with ``proposed_action='heal'`` and
``applied=0`` — ALWAYS 0: the original failure remains the official
test outcome, CI never silently passes due to LLM intervention — and
runs the fix as a *side experiment* (a sibling copy named
``<original>::healed::<short_hash>`` tagged ``healed:true``).

Covers:
- suggestion-only contract: decision rows are always ``applied=0`` and
  the original (failed) test is never modified
- side experiment: sibling copy with exactly one body line replaced by
  the proposed assertion; outcome recorded in ``agentic_metrics`` as
  ``metric_key='heal_passed'`` with id ``<decision_id>-heal``
- quality grading: ``mutation_quality`` metric with id == decision id
  (same join key as mutate), so the Superset "healing candidates"
  chart can filter on quality >= 0.7
- safety rails identical to mutate: allow-listed keywords only, safe
  arguments only, first-lines-only parsing, persist-before-experiment,
  experiment copies never re-heal, per-test opt-in
- token budget semantics identical to #358/#359/#360
- mode precedence: flow > mutate > heal > observe

All providers are synthetic — no live Ollama.
"""

from __future__ import annotations

import copy as copy_module
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from rfc.generative_listener import (
    ALLOWED_MUTATION_KEYWORDS,
    HEAL_METRIC_ID_SUFFIX,
    HEAL_PASSED_METRIC,
    HEAL_SUGGEST_TAG,
    HEALED_MARKER_TAG,
    MUTATION_QUALITY_METRIC,
    GenerativeListener,
    _parse_heal,
)
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticHarness

T0 = "2026-06-12T00:00:00Z"
SESSION = "sess-gen-heal-1"

HEAL_RESPONSE = "1\nShould Be Equal    ${answer}    Paris"
GRADE_OK = '{"score": 0.9, "reason": "plausible fix"}'
GRADE_LOW = '{"score": 0.2, "reason": "weak fix"}'
HEALED_NAME_RE = re.compile(r"^t1::healed::[0-9a-f]{8}$")

# ---------------------------------------------------------------------------
# Helpers — synthetic provider and a minimal running-model stand-in
# (same shape as tests/test_generative_listener_mutate.py)
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
    suite = SimpleNamespace(name="Heal Suite", tests=[], suites=[])
    suite.tests = [FakeTest(n, list(tags), parent=suite) for n in test_names]
    return suite


def _run_suite(
    listener: GenerativeListener,
    suite: SimpleNamespace,
    outcomes: Dict[str, str],
    default_outcome: str = "PASS",
) -> List[FakeTest]:
    """Drive the listener through ``suite``, honouring dynamic insertion."""
    executed: List[FakeTest] = []
    listener.start_suite(suite, SimpleNamespace())
    index = 0
    while index < len(suite.tests):
        test = suite.tests[index]
        listener.start_test(test, SimpleNamespace())
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
        "RFC_GENERATIVE_MUTATE_PROMPTS",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SESSION_ID", SESSION)
    return cwd


def _listener(tmp_path, provider: SyntheticProvider) -> GenerativeListener:
    return GenerativeListener(database_url=_db_url(tmp_path), provider=provider)


# ---------------------------------------------------------------------------
# heal happy path — suggestion recorded, side experiment runs
# ---------------------------------------------------------------------------


class TestHealRunsSideExperiment:
    def test_failure_inserts_named_tagged_experiment(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2  # original + side experiment
        experiment = executed[1]
        assert HEALED_NAME_RE.match(experiment.name), experiment.name
        assert HEALED_MARKER_TAG in experiment.tags
        # exactly the targeted body line was replaced by the proposed fix
        assert len(experiment.body) == 1
        assert experiment.body[0].name == "Should Be Equal"
        assert experiment.body[0].args == ["${answer}", "Paris"]
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1
        assert rows[0].test_name == "t1"
        assert "Should Be Equal" in rows[0].response_text

    def test_decision_is_never_applied(self, clean_env, tmp_path):
        """Suggestion-only by design: applied=0 ALWAYS, even when the
        side experiment was inserted and ran — the original failure
        remains the official test outcome."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1
        assert rows[0].applied == 0

    def test_original_test_is_not_modified(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        original = suite.tests[0]
        before = [(kw.name, list(kw.args)) for kw in original.body]
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        after = [(kw.name, list(kw.args)) for kw in original.body]
        assert before == after
        assert HEALED_MARKER_TAG not in original.tags

    def test_heal_outcome_recorded_as_heal_passed_metric(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        # original fails, experiment passes (default outcome PASS)
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        metrics = db.get_metrics(SESSION, metric_key=HEAL_PASSED_METRIC)
        assert len(metrics) == 1
        assert metrics[0].metric_value == pytest.approx(1.0)
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert metrics[0].id == rows[0].id + HEAL_METRIC_ID_SUFFIX

    def test_failed_experiment_records_heal_passed_zero(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        # everything fails, including the experiment
        _run_suite(
            _listener(tmp_path, provider),
            suite,
            {"t1": "FAIL"},
            default_outcome="FAIL",
        )
        metrics = db.get_metrics(SESSION, metric_key=HEAL_PASSED_METRIC)
        assert len(metrics) == 1
        assert metrics[0].metric_value == pytest.approx(0.0)
        # the failing experiment never triggers a second heal
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1

    def test_heal_prompt_shows_numbered_body_and_failure(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        prompt = provider.prompts[0]
        assert "Original Keyword" in prompt  # the test body is shown
        assert "boom" in prompt  # the failure message is shown
        for keyword in ALLOWED_MUTATION_KEYWORDS:
            assert keyword in prompt


# ---------------------------------------------------------------------------
# quality grading → agentic_metrics (same join key as mutate)
# ---------------------------------------------------------------------------


class TestHealQualityGrading:
    def test_quality_metric_written_with_decision_id(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        metrics = db.get_metrics(SESSION, metric_key=MUTATION_QUALITY_METRIC)
        assert len(metrics) == 1
        assert metrics[0].metric_value == pytest.approx(0.9)
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert metrics[0].id == rows[0].id  # join key: metric id == decision id

    def test_grader_failure_does_not_block_experiment(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, "not json at all"])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2  # experiment still ran
        assert db.get_metrics(SESSION, metric_key=MUTATION_QUALITY_METRIC) == []
        # heal outcome still recorded
        metrics = db.get_metrics(SESSION, metric_key=HEAL_PASSED_METRIC)
        assert len(metrics) == 1


# ---------------------------------------------------------------------------
# safety rails
# ---------------------------------------------------------------------------


class TestHealSafety:
    def test_passed_test_is_not_healed(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_skipped_test_is_not_healed(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "SKIP"})
        assert len(executed) == 1
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_disallowed_keyword_recorded_not_run(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["1\nRun Process    rm    -rf    /"])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1  # no experiment inserted
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1
        assert rows[0].applied == 0
        assert provider.calls == 1  # no grading call for a rejected fix

    def test_injected_argument_recorded_not_run(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(
            responses=["1\nShould Be Equal    ${{__import__('os').getcwd()}}    x"]
        )
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1
        assert rows[0].applied == 0

    def test_out_of_range_line_recorded_not_run(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(
            responses=["99\nShould Be Equal    ${answer}    Paris"]
        )
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])  # body has 1 line
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1
        assert rows[0].applied == 0

    def test_unparseable_response_recorded_not_run(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["the test is probably flaky"])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1
        assert rows[0].applied == 0

    def test_untagged_test_in_heal_suite_is_not_healed(self, clean_env, tmp_path):
        """Per-test opt-in: a heal-mode suite never heals untagged tests."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = SimpleNamespace(name="Mixed Suite", tests=[], suites=[])
        suite.tests = [
            FakeTest("t1", [HEAL_SUGGEST_TAG], parent=suite),
            FakeTest("u1", ["tier:0"], parent=suite),
        ]
        executed = _run_suite(_listener(tmp_path, provider), suite, {"u1": "FAIL"})
        assert len(executed) == 2  # u1 failed but is untagged: no experiment
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_no_experiment_when_decision_cannot_be_persisted(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        listener = _listener(tmp_path, provider)
        suite = _suite([HEAL_SUGGEST_TAG], ["t1", "t2"])
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
            "experiment must be withheld when the decision row cannot be persisted"
        )

    def test_copy_build_failure_inserts_nothing(self, clean_env, tmp_path, monkeypatch):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])

        def broken_deepcopy(self):
            raise RuntimeError("deepcopy exploded")

        monkeypatch.setattr(FakeTest, "deepcopy", broken_deepcopy)
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1  # nothing inserted
        rows = db.get_decisions(SESSION, proposed_action="heal")
        assert len(rows) == 1  # suggestion still recorded
        assert rows[0].applied == 0
        assert db.get_metrics(SESSION, metric_key=HEAL_PASSED_METRIC) == []

    def test_budget_exhaustion_silences_healing(self, clean_env, tmp_path, monkeypatch):
        monkeypatch.setenv("RFC_GENERATIVE_BUDGET_TOKENS", "100")
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(
            responses=[HEAL_RESPONSE, GRADE_OK], tokens_per_call=10_000
        )
        suite = _suite([HEAL_SUGGEST_TAG], ["t1", "t2", "t3"])
        _run_suite(
            _listener(tmp_path, provider),
            suite,
            {"t1": "FAIL", "t2": "FAIL", "t3": "FAIL"},
        )
        rows = db.get_decisions(SESSION)
        exhausted = [r for r in rows if r.proposed_action == "budget_exhausted"]
        assert len(exhausted) == 1
        assert exhausted[0].applied == 0
        assert provider.calls == 1  # only the first (budget-blowing) call

    def test_untagged_suite_is_inert(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite(["tier:0"], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_no_harness_row_disables_healing(self, clean_env, tmp_path):
        db = HarnessDatabase(database_url=_db_url(tmp_path))  # no seeded row
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([HEAL_SUGGEST_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []


# ---------------------------------------------------------------------------
# mode precedence — flow > mutate > heal > observe
# ---------------------------------------------------------------------------


class TestModePrecedence:
    def test_flow_tag_takes_precedence_over_heal(self, clean_env, tmp_path):
        from rfc.generative_listener import GENERATIVE_FLOW_TAG

        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["none"])
        suite = _suite([GENERATIVE_FLOW_TAG, HEAL_SUGGEST_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        rows = db.get_decisions(SESSION)
        assert len(rows) == 1
        assert rows[0].proposed_action == "none"  # flow prompt, not heal

    def test_mutate_tag_takes_precedence_over_heal(self, clean_env, tmp_path):
        from rfc.generative_listener import GENERATIVE_MUTATE_TAG

        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG, HEAL_SUGGEST_TAG], ["t1"])
        # mutate mode ignores failures entirely; heal must not kick in
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1
        assert db.get_decisions(SESSION, proposed_action="heal") == []

    def test_heal_tag_takes_precedence_over_observe(self, clean_env, tmp_path):
        from rfc.generative_listener import GENERATIVE_OBSERVE_TAG

        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([GENERATIVE_OBSERVE_TAG, HEAL_SUGGEST_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        rows = db.get_decisions(SESSION)
        assert rows
        assert all(r.proposed_action == "heal" for r in rows)

    def test_observe_suite_never_heals(self, clean_env, tmp_path):
        from rfc.generative_listener import GENERATIVE_OBSERVE_TAG

        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[HEAL_RESPONSE, GRADE_OK])
        suite = _suite([GENERATIVE_OBSERVE_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2  # nothing inserted
        rows = db.get_decisions(SESSION)
        assert rows
        assert all(r.proposed_action == "observe" for r in rows)
        assert all(r.applied == 0 for r in rows)


# ---------------------------------------------------------------------------
# externalized prompts resource
# ---------------------------------------------------------------------------


class TestHealPromptResource:
    def test_repo_resource_ships_heal_templates(self, monkeypatch):
        from rfc.generative_listener import (
            MUTATE_PROMPTS_RESOURCE,
            _load_mutate_prompts,
        )

        monkeypatch.delenv("RFC_GENERATIVE_MUTATE_PROMPTS", raising=False)
        assert MUTATE_PROMPTS_RESOURCE.exists()
        prompts = _load_mutate_prompts()
        template = prompts["HEAL_PROMPT_TEMPLATE"]
        for placeholder in (
            "{test}",
            "{suite}",
            "{message}",
            "{rfc_data}",
            "{body}",
            "{allowed_keywords}",
        ):
            assert placeholder in template
        question = prompts["HEAL_GRADER_QUESTION"]
        for placeholder in ("{test}", "{suite}", "{message}", "{assertion}"):
            assert placeholder in question
        assert prompts["HEAL_GRADER_EXPECTED"].strip()

    def test_missing_resource_falls_back_to_builtins(self, monkeypatch, tmp_path):
        from rfc.generative_listener import _load_mutate_prompts

        monkeypatch.setenv(
            "RFC_GENERATIVE_MUTATE_PROMPTS", str(tmp_path / "missing.resource")
        )
        prompts = _load_mutate_prompts()
        assert "{allowed_keywords}" in prompts["HEAL_PROMPT_TEMPLATE"]
        assert "{assertion}" in prompts["HEAL_GRADER_QUESTION"]


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


class TestParseHeal:
    def test_line_number_and_assertion_parse(self):
        assert _parse_heal("1\nShould Contain    ${answer}    Paris") == (
            1,
            "Should Contain",
            ["${answer}", "Paris"],
        )

    def test_decorated_line_number_parses(self):
        assert _parse_heal("**2.**\nShould Not Be Empty    ${answer}") == (
            2,
            "Should Not Be Empty",
            ["${answer}"],
        )

    def test_blank_lines_between_parts_ok(self):
        assert _parse_heal("1\n\nShould Contain    ${answer}    ok") == (
            1,
            "Should Contain",
            ["${answer}", "ok"],
        )

    def test_non_integer_first_line_rejected(self):
        assert _parse_heal("first\nShould Contain    ${answer}    x") is None

    def test_zero_or_negative_line_rejected(self):
        assert _parse_heal("0\nShould Contain    ${answer}    x") is None
        assert _parse_heal("-1\nShould Contain    ${answer}    x") is None

    def test_missing_assertion_line_rejected(self):
        assert _parse_heal("1") is None
        assert _parse_heal("") is None

    def test_disallowed_keyword_rejected(self):
        assert _parse_heal("1\nRun Process    rm    -rf    /") is None

    def test_unsafe_argument_rejected(self):
        evil = "1\nShould Be Equal    ${{__import__('os').system('x')}}    0"
        assert _parse_heal(evil) is None

    def test_trailing_prose_ignored(self):
        parsed = _parse_heal(
            "1\nShould Contain    ${answer}    Paris\nbecause the city is Paris"
        )
        assert parsed == (1, "Should Contain", ["${answer}", "Paris"])
