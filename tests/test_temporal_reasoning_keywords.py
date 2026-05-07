"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _response_contains,
)


class TestResponseContains:
    def test_exact_match(self) -> None:
        assert _response_contains("The answer is March 31", "March 31") is True

    def test_case_insensitive(self) -> None:
        assert _response_contains("march 31 is correct", "March 31") is True

    def test_not_found(self) -> None:
        assert _response_contains("The answer is April 1", "March 31") is False

    def test_substring_match(self) -> None:
        assert _response_contains("The date is March 31, 2024", "March 31") is True

    def test_empty_response(self) -> None:
        assert _response_contains("", "March 31") is False

    def test_empty_expected(self) -> None:
        assert _response_contains("anything", "") is True


class TestTemporalReasoningKeywordsInit:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_default_init(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        TemporalReasoningKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_custom_timeout(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        TemporalReasoningKeywords(timeout=120)
        mock_create.assert_called_once_with(timeout=120, max_retries=2)


class TestRunTemporalExactMatchTest:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_passes_when_expected_in_response(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "The answer is March 31, 2024"

        result = kw.run_temporal_exact_match_test(
            question="What date is 90 days after January 1, 2024?",
            expected="March 31",
        )

        assert result["score"] == 1.0
        assert result["passed"] is True
        assert result["expected"] == "March 31"

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_fails_when_expected_not_in_response(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "The answer is April 1, 2024"

        result = kw.run_temporal_exact_match_test(
            question="What date is 90 days after January 1, 2024?",
            expected="March 31",
        )

        assert result["score"] == 0.0
        assert result["passed"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_case_insensitive_match(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "thursday"

        result = kw.run_temporal_exact_match_test(
            question="What day of the week is July 4, 2024?",
            expected="Thursday",
        )

        assert result["passed"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_raises_on_empty_question(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        with pytest.raises(ValueError, match="question must not be empty"):
            kw.run_temporal_exact_match_test(question="   ", expected="March 31")

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_raises_on_empty_expected(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        with pytest.raises(ValueError, match="expected must not be empty"):
            kw.run_temporal_exact_match_test(question="A question?", expected="   ")


class TestRunTemporalGradedTest:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_passes_when_score_above_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "Apollo 11 moon landing"
        mock_grade = MagicMock()
        mock_grade.score = 0.9
        mock_grade.reason = "correct event identified"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_temporal_graded_test(
            question="Which happened first?",
            expected="Apollo 11 moon landing",
        )

        assert result["score"] == 0.9
        assert result["passed"] is True
        assert result["reason"] == "correct event identified"

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_fails_when_score_below_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "Berlin Wall"
        mock_grade = MagicMock()
        mock_grade.score = 0.1
        mock_grade.reason = "wrong event"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_temporal_graded_test(
            question="Which happened first?",
            expected="Apollo 11 moon landing",
            min_score=0.5,
        )

        assert result["passed"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_raises_on_empty_question(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        with pytest.raises(ValueError, match="question must not be empty"):
            kw.run_temporal_graded_test(question="", expected="something")
