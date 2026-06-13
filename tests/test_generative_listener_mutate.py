"""Tests for rfc.generative_listener (#360) — ``generative:mutate`` test mutation.

Phase 3 of the Agentic Stack Tracker, highest-risk generative behavior:
when a suite is tagged ``generative:mutate`` the listener may generate a
new assertion inline, execute it as a sibling test (so it gets its own
``test_runs`` row from the regular results listener), and grade the
mutation's quality in parallel.

Covers:
- mutation: a sibling copy named ``<original>::mutated::<short_hash>``
  tagged ``mutated:true``, original body preserved, one allow-listed
  assertion appended; decision row ``proposed_action='mutate'``,
  ``applied=1``
- parallel grader: ``Grade Answer`` core scores the mutation, written to
  ``agentic_metrics`` as ``metric_key='mutation_quality'`` with the
  metric id equal to the decision id (join key)
- safety rails: non-allow-listed keywords and unparseable responses are
  recorded ``applied=0`` and never executed; mutated copies never
  re-mutate; per-test opt-in scoping; persist-before-apply; grader
  failure never blocks the (already recorded) mutation
- token budget semantics identical to #358/#359 (one ``budget_exhausted``
  marker, then silence — grading included)
- ``generative:observe`` / ``generative:flow`` behaviour unchanged

All providers are synthetic — no live Ollama.
"""

from __future__ import annotations

import copy as copy_module
import re
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from rfc.generative_listener import (
    ALLOWED_MUTATION_KEYWORDS,
    GENERATIVE_MUTATE_TAG,
    MUTATED_MARKER_TAG,
    MUTATION_QUALITY_METRIC,
    GenerativeListener,
    _parse_mutation,
)
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticHarness

T0 = "2026-06-12T00:00:00Z"
SESSION = "sess-gen-mutate-1"

ASSERTION = "Should Contain    ${answer}    Paris"
GRADE_OK = '{"score": 0.9, "reason": "strict and meaningful"}'
MUTATED_NAME_RE = re.compile(r"^t1::mutated::[0-9a-f]{8}$")

# ---------------------------------------------------------------------------
# Helpers — synthetic provider and a minimal running-model stand-in
# (same shape as tests/test_generative_listener_flow.py)
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
    suite = SimpleNamespace(name="Mutate Suite", tests=[], suites=[])
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
# mutation happy path
# ---------------------------------------------------------------------------


class TestMutateInsertsSibling:
    def test_mutation_inserts_named_tagged_sibling(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(
            responses=[ASSERTION, GRADE_OK, ASSERTION, GRADE_OK]
        )
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 4  # t1, mutated copy, t2, mutated copy of t2
        mutated = executed[1]
        assert MUTATED_NAME_RE.match(mutated.name), mutated.name
        assert MUTATED_MARKER_TAG in mutated.tags
        # original body preserved, allow-listed assertion appended
        assert mutated.body[0].name == "Original Keyword"
        assert mutated.body[-1].name == "BuiltIn.Should Contain"
        assert mutated.body[-1].args == ["${answer}", "Paris"]
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert len(rows) == 2
        assert rows[0].applied == 1
        assert rows[0].test_name == "t1"
        assert ASSERTION.split("    ")[0] in rows[0].response_text

    def test_failed_test_is_not_mutated(self, clean_env, tmp_path):
        """Robot stops a test at the first failing keyword, so an assertion
        appended after a failing body would never execute — recording it as
        applied=1 would be a lie (Codex P2 on PR #501)."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 1  # nothing inserted
        assert provider.calls == 0  # no budget spent on unreachable assertions
        assert db.get_decisions(SESSION) == []

    def test_skipped_test_is_not_mutated(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "SKIP"})
        assert len(executed) == 1
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_mutated_copy_never_remutates(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 2  # original + one mutation, no recursion
        assert provider.calls == 2  # one mutation prompt + one grading call
        assert len(db.get_decisions(SESSION, proposed_action="mutate")) == 1

    def test_mutation_prompt_shows_body_and_allowed_keywords(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {})
        prompt = provider.prompts[0]
        assert "Original Keyword" in prompt  # the test body is shown
        for keyword in ALLOWED_MUTATION_KEYWORDS:
            assert keyword in prompt


# ---------------------------------------------------------------------------
# parallel grader → agentic_metrics
# ---------------------------------------------------------------------------


class TestMutationQualityGrading:
    def test_quality_metric_written_with_decision_id(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {})
        metrics = db.get_metrics(SESSION, metric_key=MUTATION_QUALITY_METRIC)
        assert len(metrics) == 1
        assert metrics[0].metric_value == pytest.approx(0.9)
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert metrics[0].id == rows[0].id  # join key: metric id == decision id

    def test_grader_failure_does_not_block_mutation(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, "not json at all"])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 2  # mutation still ran
        assert db.get_metrics(SESSION, metric_key=MUTATION_QUALITY_METRIC) == []
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert len(rows) == 1
        assert rows[0].applied == 1

    def test_grading_tokens_drain_the_budget(self, clean_env, tmp_path, monkeypatch):
        monkeypatch.setenv("RFC_GENERATIVE_BUDGET_TOKENS", "120")
        db = _seed_harness(tmp_path)
        # 100 tokens for the mutation + 100 for grading > 120 budget
        provider = SyntheticProvider(
            responses=[ASSERTION, GRADE_OK], tokens_per_call=100
        )
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1", "t2"])
        _run_suite(_listener(tmp_path, provider), suite, {})
        rows = db.get_decisions(SESSION)
        exhausted = [r for r in rows if r.proposed_action == "budget_exhausted"]
        assert len(exhausted) == 1
        # only t1 was mutated; t2's mutation was suppressed by the budget
        assert len([r for r in rows if r.proposed_action == "mutate"]) == 1


# ---------------------------------------------------------------------------
# safety rails
# ---------------------------------------------------------------------------


class TestMutateSafety:
    def test_disallowed_keyword_recorded_not_applied(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["Run Process    rm    -rf    /"])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1  # nothing inserted
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert len(rows) == 1
        assert rows[0].applied == 0
        assert provider.calls == 1  # no grading call for a rejected mutation

    def test_injected_argument_recorded_not_applied(self, clean_env, tmp_path):
        """Allow-listed keyword with an executable argument is rejected
        end-to-end (Codex P1 on PR #501)."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(
            responses=["Should Be Equal    ${{__import__('os').getcwd()}}    x"]
        )
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1  # nothing inserted
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert len(rows) == 1
        assert rows[0].applied == 0
        assert provider.calls == 1  # no grading call for a rejected mutation

    def test_unparseable_response_recorded_not_applied(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["this test looks fine to me"])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert len(rows) == 1
        assert rows[0].applied == 0

    def test_untagged_test_in_mutate_suite_is_not_mutated(self, clean_env, tmp_path):
        """Per-test opt-in: a mutate-mode suite never mutates untagged tests."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = SimpleNamespace(name="Mixed Suite", tests=[], suites=[])
        suite.tests = [
            FakeTest("t1", [GENERATIVE_MUTATE_TAG], parent=suite),
            FakeTest("u1", ["tier:0"], parent=suite),
        ]
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        names = [t.name for t in executed]
        assert len(executed) == 3  # t1, t1 mutation, u1 — u1 untouched
        assert names[2] == "u1"
        assert len(db.get_decisions(SESSION, proposed_action="mutate")) == 1

    def test_untagged_sibling_suite_failure_is_inert(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        listener = _listener(tmp_path, provider)
        tagged = _suite([GENERATIVE_MUTATE_TAG], ["tagged-test"])
        untagged = _suite([], ["plain-test"])
        top = SimpleNamespace(name="Top", tests=[], suites=[tagged, untagged])
        listener.start_suite(top, SimpleNamespace())
        before = len(untagged.tests)
        listener.end_test(
            untagged.tests[0],
            SimpleNamespace(status="PASS", passed=True, message=""),
        )
        assert len(untagged.tests) == before

    def test_no_mutation_when_decision_cannot_be_persisted(self, clean_env, tmp_path):
        _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        listener = _listener(tmp_path, provider)
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1", "t2"])
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
            SimpleNamespace(status="PASS", passed=True, message=""),
        )
        assert len(suite.tests) == before, (
            "run must not be mutated when the decision row cannot be persisted"
        )

    def test_budget_exhaustion_silences_mutation(
        self, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("RFC_GENERATIVE_BUDGET_TOKENS", "100")
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(
            responses=[ASSERTION, GRADE_OK], tokens_per_call=10_000
        )
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1", "t2", "t3"])
        _run_suite(_listener(tmp_path, provider), suite, {})
        rows = db.get_decisions(SESSION)
        exhausted = [r for r in rows if r.proposed_action == "budget_exhausted"]
        assert len(exhausted) == 1
        assert exhausted[0].applied == 0
        assert provider.calls == 1  # only the first (budget-blowing) call

    def test_untagged_suite_is_inert(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite(["tier:0"], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []

    def test_no_harness_row_disables_mutation(self, clean_env, tmp_path):
        db = HarnessDatabase(database_url=_db_url(tmp_path))  # no seeded row
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1
        assert provider.calls == 0
        assert db.get_decisions(SESSION) == []


# ---------------------------------------------------------------------------
# observe stays read-only; flow precedence
# ---------------------------------------------------------------------------


class TestModeInteraction:
    def test_observe_suite_never_mutates(self, clean_env, tmp_path):
        from rfc.generative_listener import GENERATIVE_OBSERVE_TAG

        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_OBSERVE_TAG], ["t1", "t2"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        assert len(executed) == 2  # nothing inserted
        rows = db.get_decisions(SESSION)
        assert rows
        assert all(r.applied == 0 for r in rows)
        assert all(r.proposed_action == "observe" for r in rows)

    def test_flow_tag_takes_precedence_over_mutate(self, clean_env, tmp_path):
        from rfc.generative_listener import GENERATIVE_FLOW_TAG

        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=["none"])
        suite = _suite([GENERATIVE_FLOW_TAG, GENERATIVE_MUTATE_TAG], ["t1"])
        _run_suite(_listener(tmp_path, provider), suite, {"t1": "FAIL"})
        rows = db.get_decisions(SESSION)
        assert len(rows) == 1
        assert rows[0].proposed_action == "none"  # flow prompt, not mutate


# ---------------------------------------------------------------------------
# externalized prompts resource
# ---------------------------------------------------------------------------


class TestPromptResource:
    def test_repo_resource_parses_with_all_placeholders(self, monkeypatch):
        from rfc.generative_listener import (
            MUTATE_PROMPTS_RESOURCE,
            _load_mutate_prompts,
        )

        monkeypatch.delenv("RFC_GENERATIVE_MUTATE_PROMPTS", raising=False)
        assert MUTATE_PROMPTS_RESOURCE.exists(), (
            "src/rfc/resources/generative_mutate_prompts.resource must ship in-repo"
        )
        prompts = _load_mutate_prompts()
        template = prompts["MUTATION_PROMPT_TEMPLATE"]
        assert "\n" in template  # SEPARATOR=\n was honoured, not space-joined
        for placeholder in (
            "{test}",
            "{suite}",
            "{status}",
            "{message}",
            "{rfc_data}",
            "{body}",
            "{allowed_keywords}",
        ):
            assert placeholder in template
        question = prompts["MUTATION_GRADER_QUESTION"]
        for placeholder in ("{test}", "{suite}", "{status}", "{assertion}"):
            assert placeholder in question
        assert prompts["MUTATION_GRADER_EXPECTED"].strip()

    def test_override_resource_is_actually_parsed(self, monkeypatch, tmp_path):
        """An edited resource changes the prompt — proof we parse the file
        rather than silently using the built-in fallback."""
        from rfc.generative_listener import _load_mutate_prompts

        resource = tmp_path / "custom.resource"
        resource.write_text(
            "*** Variables ***\n"
            "${MUTATION_PROMPT_TEMPLATE}    SEPARATOR=\\n\n"
            "...    CUSTOM PROMPT {test} {suite} {status} {message}\n"
            "...    {rfc_data} {body} {allowed_keywords} \\${answer}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("RFC_GENERATIVE_MUTATE_PROMPTS", str(resource))
        prompts = _load_mutate_prompts()
        template = prompts["MUTATION_PROMPT_TEMPLATE"]
        assert template.startswith("CUSTOM PROMPT {test}")
        assert "\n{rfc_data}" in template  # SEPARATOR=\n honoured
        assert "${answer}" in template  # robot \${ escape unescaped
        # variables not present in the file keep their built-in defaults
        assert "{assertion}" in prompts["MUTATION_GRADER_QUESTION"]

    def test_template_with_literal_robot_variable_does_not_break_filling(
        self, clean_env, tmp_path, monkeypatch
    ):
        """A custom template containing a literal Robot variable like
        ``${answer}`` must not blow up placeholder filling (Codex P2 on
        PR #501: str.format would raise KeyError on ``{answer}``)."""
        resource = tmp_path / "custom.resource"
        resource.write_text(
            "*** Variables ***\n"
            "${MUTATION_PROMPT_TEMPLATE}    SEPARATOR=\\n\n"
            "...    Mutate test {test} (e.g. assert on \\${answer}).\n"
            "...    Allowed: {allowed_keywords}. Body: {body}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("RFC_GENERATIVE_MUTATE_PROMPTS", str(resource))
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 2  # mutation applied, no KeyError swallowed
        prompt = provider.prompts[0]
        assert prompt.startswith("Mutate test t1")
        assert "${answer}" in prompt  # the literal variable survived filling
        assert len(db.get_decisions(SESSION, proposed_action="mutate")) == 1

    def test_missing_resource_falls_back_to_builtins(self, monkeypatch, tmp_path):
        from rfc.generative_listener import _load_mutate_prompts

        monkeypatch.setenv(
            "RFC_GENERATIVE_MUTATE_PROMPTS", str(tmp_path / "missing.resource")
        )
        prompts = _load_mutate_prompts()
        assert "{allowed_keywords}" in prompts["MUTATION_PROMPT_TEMPLATE"]
        assert "{assertion}" in prompts["MUTATION_GRADER_QUESTION"]


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


class TestParseMutation:
    def test_allowed_keyword_parses(self):
        assert _parse_mutation("Should Contain    ${answer}    Paris") == (
            "Should Contain",
            ["${answer}", "Paris"],
        )

    def test_case_insensitive_keyword_canonicalised(self):
        assert _parse_mutation("should be equal    ${answer}    Paris") == (
            "Should Be Equal",
            ["${answer}", "Paris"],
        )

    def test_markdown_decoration_stripped(self):
        assert _parse_mutation("`Should Not Be Empty    ${answer}`") == (
            "Should Not Be Empty",
            ["${answer}"],
        )

    def test_first_line_only(self):
        parsed = _parse_mutation(
            "Should Contain    ${answer}    Paris\nRun Process    rm    -rf"
        )
        assert parsed == ("Should Contain", ["${answer}", "Paris"])

    def test_disallowed_keyword_rejected(self):
        assert _parse_mutation("Run Process    rm    -rf    /") is None
        assert _parse_mutation("Evaluate    __import__('os').system('x')") is None

    def test_missing_args_rejected(self):
        assert _parse_mutation("Should Contain") is None

    def test_prose_rejected(self):
        assert _parse_mutation("this test looks fine to me") is None
        assert _parse_mutation("") is None

    def test_inline_python_evaluation_in_args_rejected(self):
        """Codex P1 on PR #501: Robot evaluates ${{...}} inline Python in
        ANY argument, so the keyword allow-list alone is not enough."""
        evil = "Should Be Equal    ${{__import__('os').system('rm -rf /')}}    0"
        assert _parse_mutation(evil) is None

    def test_extended_and_env_variable_args_rejected(self):
        # extended syntax can call properties / index into objects
        assert _parse_mutation("Should Contain    ${obj.attr}    x") is None
        assert _parse_mutation("Should Contain    ${list[0]}    x") is None
        # environment, list, and dict variables are not plain values either
        assert _parse_mutation("Should Contain    %{HOME}    x") is None
        assert _parse_mutation("Should Contain    @{items}    x") is None
        assert _parse_mutation("Should Contain    &{map}    x") is None
        # nested variables resolve inner-out — also rejected
        assert _parse_mutation("Should Contain    ${a${b}}    x") is None

    def test_simple_variables_and_regex_braces_still_allowed(self):
        assert _parse_mutation("Should Contain    ${answer}    Paris") is not None
        assert _parse_mutation("Should Contain    ${LLM RESPONSE}    ok") is not None
        # literal braces that are NOT Robot variable syntax stay legal
        assert _parse_mutation("Should Contain    ${answer}    \\d{3}") == (
            "Should Contain",
            ["${answer}", "\\d{3}"],
        )


class TestAppliedTruthfulness:
    """applied=1 must mean the copy really exists in the suite (#501)."""

    def test_copy_build_failure_records_applied_zero(
        self, clean_env, tmp_path, monkeypatch
    ):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])

        def broken_deepcopy(self):
            raise RuntimeError("deepcopy exploded")

        monkeypatch.setattr(FakeTest, "deepcopy", broken_deepcopy)
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1  # nothing inserted
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert len(rows) == 1
        assert rows[0].applied == 0, (
            "decision must not claim applied=1 when the mutated copy could not be built"
        )


# ---------------------------------------------------------------------------
# post-merge hardening (#516, Codex round 3 on PR #501)
# ---------------------------------------------------------------------------


class TestPostMergeHardening501:
    def test_inserted_assertion_is_builtin_qualified(self, clean_env, tmp_path):
        """A user keyword named `Should Be Equal` would shadow the BuiltIn at
        resolution time; the allow-list checks the name but cannot control
        resolution order. Explicit `BuiltIn.` qualification closes the
        code-execution bypass (Codex P1, #516)."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        mutated = executed[1]
        assert mutated.body[-1].name == "BuiltIn.Should Contain"
        assert db.get_decisions(SESSION, proposed_action="mutate")[0].applied == 1

    def test_should_match_regexp_is_not_allow_listed(self):
        """The model controls the regex argument; a catastrophic pattern like
        `(a+)+$` can hang the runner (ReDoS, Codex P2, #516)."""
        from rfc.generative_listener import ALLOWED_MUTATION_KEYWORDS

        assert "Should Match Regexp" not in ALLOWED_MUTATION_KEYWORDS

    def test_parse_mutation_rejects_should_match_regexp(self):
        from rfc.generative_listener import _parse_mutation

        assert _parse_mutation("Should Match Regexp    ${answer}    (a+)+$") is None

    def test_prompts_resource_ships_inside_package(self):
        """The default template must resolve inside the installed `rfc`
        package, not via repo-root-relative paths that do not exist in a
        wheel deployment (Codex P2, #516)."""
        import rfc
        from rfc.generative_listener import MUTATE_PROMPTS_RESOURCE

        package_dir = Path(rfc.__file__).resolve().parent
        assert MUTATE_PROMPTS_RESOURCE.is_relative_to(package_dir)
        assert MUTATE_PROMPTS_RESOURCE.exists()

    def test_mutation_blocked_when_suite_shadows_qualified_builtin(
        self, clean_env, tmp_path
    ):
        """RF resolves suite-file user keywords before explicit library
        names, so a user keyword literally named `BuiltIn.Should Contain`
        would still hijack the qualified call (Codex P1 round 2, #516).
        Such collisions must record applied=0 and insert nothing."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        suite.resource = SimpleNamespace(
            keywords=[SimpleNamespace(name="BuiltIn.Should Contain")]
        )
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1  # no sibling inserted
        rows = db.get_decisions(SESSION, proposed_action="mutate")
        assert len(rows) == 1
        assert rows[0].applied == 0

    def test_mutation_blocked_when_suite_shadows_bare_name(self, clean_env, tmp_path):
        """Same for the unqualified name, matched with Robot's keyword-name
        normalization (case/space/underscore insensitive)."""
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(responses=[ASSERTION, GRADE_OK])
        suite = _suite([GENERATIVE_MUTATE_TAG], ["t1"])
        suite.resource = SimpleNamespace(
            keywords=[SimpleNamespace(name="should_CONTAIN")]
        )
        executed = _run_suite(_listener(tmp_path, provider), suite, {})
        assert len(executed) == 1
        assert db.get_decisions(SESSION, proposed_action="mutate")[0].applied == 0
