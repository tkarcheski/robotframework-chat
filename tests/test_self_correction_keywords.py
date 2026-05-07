"""Tests for rfc.self_correction_keywords.SelfCorrectionKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.self_correction_keywords import (
    SelfCorrectionKeywords,
    _any_marker_found,
)


class TestAnyMarkerFound:
    def test_single_marker_found(self) -> None:
        assert _any_marker_found("The correct answer is 136", ["136"]) is True

    def test_first_marker_found(self) -> None:
        assert _any_marker_found("The result is 136", ["136", "wrong"]) is True

    def test_second_marker_found(self) -> None:
        assert _any_marker_found("That is wrong", ["136", "wrong"]) is True

    def test_no_marker_found(self) -> None:
        assert _any_marker_found("The answer is unknown", ["136", "correct"]) is False

    def test_case_insensitive(self) -> None:
        assert _any_marker_found("the answer is WRONG", ["wrong"]) is True

    def test_empty_response(self) -> None:
        assert _any_marker_found("", ["136"]) is False

    def test_empty_markers_list(self) -> None:
        assert _any_marker_found("some response", []) is False


class TestSelfCorrectionKeywordsInit:
    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_default_init(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        SelfCorrectionKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)


class TestRunErrorDetectionTest:
    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_passes_when_marker_in_response(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        kw.client.generate.return_value = "The correct answer is 136, not 146."

        result = kw.run_error_detection_test(
            prompt="17 × 8 = 146 is wrong. Find and correct the error.",
            detection_markers=["136"],
        )

        assert result["score"] == 1.0
        assert result["passed"] is True
        assert "136" in result["markers_found"]

    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_fails_when_no_marker_in_response(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        kw.client.generate.return_value = "I don't see any error."

        result = kw.run_error_detection_test(
            prompt="17 × 8 = 146 is wrong. Find and correct the error.",
            detection_markers=["136", "wrong"],
        )

        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["markers_found"] == []

    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_any_marker_satisfies(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        kw.client.generate.return_value = "The multiplication is incorrect."

        result = kw.run_error_detection_test(
            prompt="Find the error.",
            detection_markers=["136", "incorrect"],
        )

        assert result["passed"] is True

    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_raises_on_empty_prompt(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        with pytest.raises(ValueError, match="prompt must not be empty"):
            kw.run_error_detection_test(prompt="   ", detection_markers=["136"])

    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_raises_on_empty_markers(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        with pytest.raises(ValueError, match="detection_markers must not be empty"):
            kw.run_error_detection_test(prompt="Find the error.", detection_markers=[])


class TestRunErrorCorrectionTest:
    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_passes_when_score_above_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        kw.client.generate.return_value = "def square(n): return n * n"
        mock_grade = MagicMock()
        mock_grade.score = 1.0
        mock_grade.reason = "correct fix applied"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_error_correction_test(
            prompt="Fix the bug: def square(n): return n + n",
            expected="n * n",
        )

        assert result["score"] == 1.0
        assert result["passed"] is True

    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_raises_on_empty_prompt(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        with pytest.raises(ValueError, match="prompt must not be empty"):
            kw.run_error_correction_test(prompt="", expected="n * n")


class TestRunLogicalFlawTest:
    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_passes_when_score_above_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        kw.client.generate.return_value = (
            "This is a post hoc ergo propter hoc fallacy."
        )
        mock_grade = MagicMock()
        mock_grade.score = 0.9
        mock_grade.reason = "correctly identified fallacy"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_logical_flaw_test(
            argument="The rooster crows before sunrise, so it causes the sun to rise.",
            expected="post hoc ergo propter hoc",
        )

        assert result["score"] == 0.9
        assert result["passed"] is True

    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_prompt_wraps_argument(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        kw.client.generate.return_value = "This is a fallacy."
        mock_grade = MagicMock()
        mock_grade.score = 0.5
        mock_grade.reason = "ok"
        kw.grader.grade.return_value = mock_grade

        kw.run_logical_flaw_test(
            argument="Roosters cause sunrise.",
            expected="fallacy",
        )

        prompt_used = kw.client.generate.call_args[0][0]
        assert "Roosters cause sunrise" in prompt_used
        assert "logical flaw" in prompt_used.lower()

    @patch("rfc.self_correction_keywords.create_provider")
    @patch("rfc.self_correction_keywords.Grader")
    def test_raises_on_empty_argument(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = SelfCorrectionKeywords()
        with pytest.raises(ValueError, match="argument must not be empty"):
            kw.run_logical_flaw_test(argument="  ", expected="fallacy")
