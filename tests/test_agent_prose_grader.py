"""Tests for rfc.agent_prose_grader and the tier:3 prose keywords (#289)."""

import json

import pytest

from rfc.agent_prose_grader import AgentProseGrader
from rfc.agent_run import AgentCommit, AgentPR, AgentQuestion, AgentRun
from rfc.agentic_coding_keywords import AgenticCodingKeywords
from rfc.exceptions import MissingEnvironmentError
from rfc.multi_grader import MultiGrader


class FakeJudge:
    """Provider stub returning a fixed score; records the prompts it saw."""

    def __init__(self, score: float, reason: str = "ok") -> None:
        self.score = score
        self.reason = reason
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"score": self.score, "reason": self.reason})


def _panel(*scores: float) -> MultiGrader:
    return MultiGrader(providers=[FakeJudge(s) for s in scores])


def _run(**overrides) -> AgentRun:
    base = dict(
        agent_id="claude-code",
        scenario_id="ambiguous_task",
        task="Clean up the metrics stuff.",
        base_branch="claude-code-staging",
        branch_name="claude/clean-metrics-cd456",
        questions=(
            AgentQuestion(
                text="metrics.py has two uncalled exports. Remove them?",
                options=("a) remove", "b) keep"),
            ),
        ),
        commits=(
            AgentCommit(
                sha="3333ccc",
                subject="test: add failing test for is_palindrome",
                files_changed=("tests/test_strings.py",),
            ),
        ),
        pr=AgentPR(
            title="feat: add is_palindrome",
            body="## How to review\nStart with src/rfc/strings.py.",
        ),
    )
    base.update(overrides)
    return AgentRun(**base)


class TestAgentProseGrader:
    def test_question_grounding_passes_prompt_context(self):
        panel = _panel(1.0, 1.0, 1.0)
        result = AgentProseGrader(panel).grade_question_grounding(_run())
        assert result.majority_score == 1.0
        prompt = panel.providers[0].prompts[0]
        assert "metrics.py has two uncalled exports" in prompt
        assert "Clean up the metrics stuff." in prompt

    def test_question_grounding_requires_questions(self):
        with pytest.raises(ValueError, match="question"):
            AgentProseGrader(_panel(1, 1, 1)).grade_question_grounding(
                _run(questions=())
            )

    def test_pr_body_grading_consensus_is_median(self):
        result = AgentProseGrader(_panel(0.0, 1.0, 1.0)).grade_pr_body(_run())
        assert result.majority_score == 1.0

    def test_pr_body_requires_pr(self):
        with pytest.raises(ValueError, match="PR"):
            AgentProseGrader(_panel(1, 1, 1)).grade_pr_body(_run(pr=None))

    def test_commit_cohesion_includes_files_changed(self):
        panel = _panel(1.0, 1.0, 1.0)
        AgentProseGrader(panel).grade_commit_cohesion(_run())
        prompt = panel.providers[0].prompts[0]
        assert "tests/test_strings.py" in prompt
        assert "test: add failing test for is_palindrome" in prompt

    def test_commit_cohesion_requires_commits(self):
        with pytest.raises(ValueError, match="commit"):
            AgentProseGrader(_panel(1, 1, 1)).grade_commit_cohesion(_run(commits=()))


class TestProseKeywords:
    @pytest.fixture()
    def keywords(self):
        return AgenticCodingKeywords()

    def test_skip_when_env_unset(self, keywords, monkeypatch):
        monkeypatch.delenv("AGENT_PROSE_GRADER_MODELS", raising=False)
        with pytest.raises(MissingEnvironmentError):
            keywords.clarifying_questions_should_be_grounded(_run())

    def test_panel_requires_three_distinct_models(self, keywords, monkeypatch):
        monkeypatch.setenv("AGENT_PROSE_GRADER_MODELS", "m1,m1:latest,M1")
        with pytest.raises(ValueError, match="3"):
            keywords.clarifying_questions_should_be_grounded(_run())

    def test_grounded_questions_pass(self, keywords, monkeypatch):
        monkeypatch.setattr(
            keywords, "_prose_judge_panel", lambda: _panel(1.0, 1.0, 1.0)
        )
        keywords.clarifying_questions_should_be_grounded(_run())

    def test_ungrounded_questions_fail_with_reasons(self, keywords, monkeypatch):
        panel = MultiGrader(
            providers=[FakeJudge(0.0, reason="no file referenced")] * 3
        )
        monkeypatch.setattr(keywords, "_prose_judge_panel", lambda: panel)
        with pytest.raises(AssertionError, match="no file referenced"):
            keywords.clarifying_questions_should_be_grounded(_run())

    def test_pr_body_threshold_is_configurable(self, keywords, monkeypatch):
        monkeypatch.setattr(
            keywords, "_prose_judge_panel", lambda: _panel(0.6, 0.6, 0.6)
        )
        keywords.pr_body_should_explain_how_to_review(_run(), threshold=0.5)
        with pytest.raises(AssertionError):
            keywords.pr_body_should_explain_how_to_review(_run(), threshold=0.7)

    def test_commits_keyword_passes(self, keywords, monkeypatch):
        monkeypatch.setattr(
            keywords, "_prose_judge_panel", lambda: _panel(1.0, 1.0, 1.0)
        )
        keywords.commits_should_match_their_changes(_run())
