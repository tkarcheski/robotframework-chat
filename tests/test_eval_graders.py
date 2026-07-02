"""Tests for the rfc.graders package — the Grader Protocol + dispatcher.

The ``llm_judge`` grader wraps the existing ``rfc.grader.Grader`` (it does NOT
reimplement grading), so its LLM client is mocked exactly as
``tests/test_grader.py`` mocks it. The exact/regex graders are pure and need
no mock.
"""

from unittest.mock import MagicMock

import pytest

from rfc.graders import get_grader
from rfc.graders.base import Grader
from rfc.graders.exact import ExactGrader
from rfc.graders.llm_judge import LLMJudgeGrader
from rfc.graders.regex import RegexGrader


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_exact_is_a_grader(self) -> None:
        assert isinstance(ExactGrader(), Grader)

    def test_regex_is_a_grader(self) -> None:
        assert isinstance(RegexGrader(), Grader)

    def test_llm_judge_is_a_grader(self) -> None:
        assert isinstance(LLMJudgeGrader(MagicMock()), Grader)

    def test_grade_returns_score_and_reason_tuple(self) -> None:
        score, reason = ExactGrader().grade({"expected_answer": "4"}, "4")
        assert isinstance(score, float)
        assert isinstance(reason, str)


# ---------------------------------------------------------------------------
# ExactGrader
# ---------------------------------------------------------------------------


class TestExactGrader:
    def test_exact_match_scores_one(self) -> None:
        score, _ = ExactGrader().grade({"expected_answer": "Paris"}, "Paris")
        assert score == 1.0

    def test_mismatch_scores_zero(self) -> None:
        score, _ = ExactGrader().grade({"expected_answer": "Paris"}, "London")
        assert score == 0.0

    def test_whitespace_is_trimmed(self) -> None:
        score, _ = ExactGrader().grade({"expected_answer": "Paris"}, "  Paris\n")
        assert score == 1.0

    def test_case_insensitive_by_default(self) -> None:
        score, _ = ExactGrader().grade({"expected_answer": "Paris"}, "paris")
        assert score == 1.0

    def test_reads_expected_key(self) -> None:
        # Accept the alternate ``expected`` field too.
        score, _ = ExactGrader().grade({"expected": "yes"}, "yes")
        assert score == 1.0


# ---------------------------------------------------------------------------
# RegexGrader
# ---------------------------------------------------------------------------


class TestRegexGrader:
    def test_pattern_match_scores_one(self) -> None:
        score, _ = RegexGrader().grade({"pattern": r"\d{3}-\d{4}"}, "call 555-1234 now")
        assert score == 1.0

    def test_no_match_scores_zero(self) -> None:
        score, _ = RegexGrader().grade({"pattern": r"^\d+$"}, "abc")
        assert score == 0.0

    def test_pattern_from_expected_answer(self) -> None:
        score, _ = RegexGrader().grade(
            {"expected_answer": r"hello.*world"}, "hello brave world"
        )
        assert score == 1.0

    def test_invalid_pattern_raises(self) -> None:
        with pytest.raises((ValueError, Exception)):
            RegexGrader().grade({"pattern": "("}, "anything")


# ---------------------------------------------------------------------------
# LLMJudgeGrader (wraps rfc.grader.Grader)
# ---------------------------------------------------------------------------


class TestLLMJudgeGrader:
    def test_delegates_to_grader_and_returns_tuple(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "correct"}'
        grader = LLMJudgeGrader(client)
        score, reason = grader.grade(
            {"problem_statement": "What is 2+2?", "expected_answer": "4"}, "4"
        )
        assert score == 1.0
        assert reason == "correct"

    def test_partial_credit_passthrough(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "partial"}'
        grader = LLMJudgeGrader(client)
        score, reason = grader.grade(
            {"problem_statement": "q", "expected_answer": "e"}, "a"
        )
        assert score == 0.5
        assert reason == "partial"

    def test_reads_question_field(self) -> None:
        # The instance ``question`` field is used as the grader question.
        client = MagicMock()
        client.generate.return_value = '{"score": 0, "reason": "wrong"}'
        grader = LLMJudgeGrader(client)
        grader.grade({"question": "Capital of France?", "expected": "Paris"}, "X")
        prompt = client.generate.call_args[0][0]
        assert "Capital of France?" in prompt

    def test_empty_actual_scores_zero_without_llm(self) -> None:
        # Mirrors Grader.grade: an empty answer scores 0 without an LLM call.
        client = MagicMock()
        grader = LLMJudgeGrader(client)
        score, _ = grader.grade({"problem_statement": "q"}, "")
        assert score == 0.0
        client.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestDispatcher:
    def test_get_exact(self) -> None:
        assert isinstance(get_grader("exact"), ExactGrader)

    def test_get_regex(self) -> None:
        assert isinstance(get_grader("regex"), RegexGrader)

    def test_get_llm_judge_requires_client(self) -> None:
        g = get_grader("llm_judge", llm_client=MagicMock())
        assert isinstance(g, LLMJudgeGrader)

    def test_get_llm_judge_without_client_raises(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            get_grader("llm_judge")

    def test_unknown_grader_raises(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            get_grader("nonexistent")

    def test_dispatched_grader_satisfies_protocol(self) -> None:
        assert isinstance(get_grader("exact"), Grader)
