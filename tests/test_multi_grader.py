"""Unit tests for multi-LLM majority-vote grader."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rfc.multi_grader import MultiGrader, MultiGradeResult


def _mock_provider(response: str) -> MagicMock:
    """Create a mock LLM provider that returns a fixed response."""
    provider = MagicMock()
    provider.generate.return_value = response
    provider.model = "test-model"
    provider.last_metrics = None
    return provider


# ---------------------------------------------------------------------------
# MultiGradeResult
# ---------------------------------------------------------------------------


class TestMultiGradeResult:
    def test_unanimous_pass(self) -> None:
        r = MultiGradeResult(
            scores=[1.0, 1.0, 1.0],
            majority_score=1.0,
            agreement_ratio=1.0,
            reasons=["good", "good", "good"],
        )
        assert r.passed
        assert r.unanimous

    def test_unanimous_fail(self) -> None:
        r = MultiGradeResult(
            scores=[0.0, 0.0, 0.0],
            majority_score=0.0,
            agreement_ratio=1.0,
            reasons=["bad", "bad", "bad"],
        )
        assert not r.passed
        assert r.unanimous

    def test_majority_pass_with_disagreement(self) -> None:
        r = MultiGradeResult(
            scores=[1.0, 1.0, 0.0],
            majority_score=1.0,
            agreement_ratio=2 / 3,
            reasons=["good", "good", "bad"],
        )
        assert r.passed
        assert not r.unanimous

    def test_partial_majority_score_counts_as_pass(self) -> None:
        r = MultiGradeResult(
            scores=[0.6, 0.6, 0.9],
            majority_score=0.6,
            agreement_ratio=0.9,
            reasons=["good", "good", "great"],
        )
        assert r.passed
        assert not r.unanimous

    def test_majority_fail_with_disagreement(self) -> None:
        r = MultiGradeResult(
            scores=[0.0, 0.0, 1.0],
            majority_score=0.0,
            agreement_ratio=2 / 3,
            reasons=["bad", "bad", "good"],
        )
        assert not r.passed
        assert not r.unanimous


# ---------------------------------------------------------------------------
# MultiGrader
# ---------------------------------------------------------------------------


class TestMultiGrader:
    def test_requires_at_least_3_providers(self) -> None:
        with pytest.raises(ValueError, match="3"):
            MultiGrader(providers=[_mock_provider(""), _mock_provider("")])

    def test_unanimous_pass(self) -> None:
        providers = [
            _mock_provider('{"score": 1, "reason": "correct"}'),
            _mock_provider('{"score": 1, "reason": "accurate"}'),
            _mock_provider('{"score": 1, "reason": "valid"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(
            question="Is this a good idea?",
            expected="yes",
            actual="A great product idea.",
            rubric="Evaluate if the response is a positive product idea.",
        )
        assert result.majority_score == 1.0
        assert result.agreement_ratio == 1.0
        assert len(result.scores) == 3

    def test_unanimous_fail(self) -> None:
        providers = [
            _mock_provider('{"score": 0, "reason": "wrong"}'),
            _mock_provider('{"score": 0, "reason": "incorrect"}'),
            _mock_provider('{"score": 0, "reason": "invalid"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(question="q", expected="e", actual="a", rubric="r")
        assert result.majority_score == 0.0
        assert result.agreement_ratio == 1.0

    def test_majority_vote_2_of_3(self) -> None:
        providers = [
            _mock_provider('{"score": 1, "reason": "good"}'),
            _mock_provider('{"score": 1, "reason": "fine"}'),
            _mock_provider('{"score": 0, "reason": "bad"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(question="q", expected="e", actual="a", rubric="r")
        assert result.majority_score == 1.0
        assert abs(result.agreement_ratio - 2 / 3) < 0.01

    def test_majority_vote_3_of_5(self) -> None:
        providers = [
            _mock_provider('{"score": 1, "reason": "a"}'),
            _mock_provider('{"score": 0, "reason": "b"}'),
            _mock_provider('{"score": 1, "reason": "c"}'),
            _mock_provider('{"score": 0, "reason": "d"}'),
            _mock_provider('{"score": 1, "reason": "e"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(question="q", expected="e", actual="a", rubric="r")
        assert result.majority_score == 1.0
        assert abs(result.agreement_ratio - 0.6) < 0.01

    def test_handles_json_in_markdown(self) -> None:
        providers = [
            _mock_provider('```json\n{"score": 1, "reason": "ok"}\n```'),
            _mock_provider('{"score": 1, "reason": "ok"}'),
            _mock_provider('<think>hmm</think>\n{"score": 1, "reason": "ok"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(question="q", expected="e", actual="a", rubric="r")
        assert result.majority_score == 1.0

    def test_invalid_json_from_one_grader_still_works(self) -> None:
        providers = [
            _mock_provider('{"score": 1, "reason": "ok"}'),
            _mock_provider("not json at all"),
            _mock_provider('{"score": 1, "reason": "ok"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(question="q", expected="e", actual="a", rubric="r")
        # Invalid response counts as score=0
        assert result.scores[1] == 0.0
        assert result.majority_score == 1.0

    def test_grade_uses_rubric_in_prompt(self) -> None:
        providers = [
            _mock_provider('{"score": 1, "reason": "ok"}'),
            _mock_provider('{"score": 1, "reason": "ok"}'),
            _mock_provider('{"score": 1, "reason": "ok"}'),
        ]
        grader = MultiGrader(providers=providers)
        grader.grade(
            question="q",
            expected="e",
            actual="a",
            rubric="Check for novelty and market viability.",
        )
        # Verify the rubric was included in the prompt sent to each provider
        for p in providers:
            call_args = p.generate.call_args[0][0]
            assert "novelty" in call_args
            assert "market viability" in call_args

    def test_fractional_scores_preserved_in_aggregation(self) -> None:
        providers = [
            _mock_provider('{"score": 0.9, "reason": "strong"}'),
            _mock_provider('{"score": 0.6, "reason": "solid"}'),
            _mock_provider('{"score": 0.6, "reason": "solid"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(question="q", expected="e", actual="a", rubric="r")
        assert result.majority_score == 0.6
        assert abs(result.agreement_ratio - 0.9) < 0.01
        assert result.passed

    def test_prompt_requests_fractional_scores(self) -> None:
        providers = [
            _mock_provider('{"score": 0.5, "reason": "ok"}'),
            _mock_provider('{"score": 0.5, "reason": "ok"}'),
            _mock_provider('{"score": 0.5, "reason": "ok"}'),
        ]
        grader = MultiGrader(providers=providers)
        grader.grade(question="q", expected="e", actual="a", rubric="r")
        prompt = providers[0].generate.call_args[0][0]
        assert "score must be a number between 0.0 and 1.0" in prompt
        assert "use partial credit" in prompt
        assert '"score": 0.0 to 1.0' in prompt

    def test_invalid_fractional_score_reports_original_value(self) -> None:
        providers = [
            _mock_provider('{"score": 1.2, "reason": "too high"}'),
            _mock_provider('{"score": 0.8, "reason": "fine"}'),
            _mock_provider('{"score": 0.8, "reason": "fine"}'),
        ]
        grader = MultiGrader(providers=providers)
        result = grader.grade(question="q", expected="e", actual="a", rubric="r")
        assert result.scores[0] == 0.0
        assert result.reasons[0] == "Invalid score value: 1.2"
