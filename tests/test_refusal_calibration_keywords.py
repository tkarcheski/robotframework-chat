"""Tests for rfc.refusal_calibration_keywords.RefusalCalibrationKeywords."""

from unittest.mock import patch

import pytest

from rfc.models import CalibrationResult
from rfc.refusal_calibration_keywords import RefusalCalibrationKeywords


def _make_result(
    is_calibrated: bool = True,
    refusal_type: str = "none",
    category: str = "medical",
) -> CalibrationResult:
    return CalibrationResult(
        is_calibrated=is_calibrated,
        refusal_type=refusal_type,
        confidence=0.9,
        category=category,
        indicators=[],
        details={},
        violation_type=None if is_calibrated else "over_refusal",
    )


class TestInit:
    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_default_init(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        assert kw.over_refusal_threshold == 0.10
        assert kw.test_results == []

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_custom_timeout(self, MockGrader, mock_create):
        RefusalCalibrationKeywords(timeout=60, max_retries=1)
        mock_create.assert_called_once_with(timeout=60, max_retries=1)


class TestThreshold:
    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_set_over_refusal_threshold(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        kw.set_over_refusal_threshold(0.05)
        assert kw.over_refusal_threshold == 0.05

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_set_threshold_string(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        kw.set_over_refusal_threshold("0.20")
        assert kw.over_refusal_threshold == 0.20


class TestRunCalibrationTestCase:
    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_run_calibrated_response(self, MockGrader, mock_create):
        mock_create.return_value.generate.return_value = "Substantive answer."
        MockGrader.return_value.grade_calibration.return_value = _make_result(
            is_calibrated=True
        )
        kw = RefusalCalibrationKeywords()
        result = kw.run_calibration_test_case(
            prompt="What is X?", description="Test", category="medical"
        )
        assert result["is_calibrated"] is True
        assert result["refusal_type"] == "none"
        assert result["category"] == "medical"
        assert len(kw.test_results) == 1

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_run_over_refused_response(self, MockGrader, mock_create):
        mock_create.return_value.generate.return_value = "I cannot help."
        MockGrader.return_value.grade_calibration.return_value = _make_result(
            is_calibrated=False, refusal_type="hard"
        )
        kw = RefusalCalibrationKeywords()
        result = kw.run_calibration_test_case(
            prompt="What is X?", category="medical"
        )
        assert result["is_calibrated"] is False
        assert result["refusal_type"] == "hard"


class TestAssertNotOverRefused:
    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_passes_when_calibrated(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        kw.assert_not_over_refused({"is_calibrated": True, "refusal_type": "none"})

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_raises_when_over_refused(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        with pytest.raises(AssertionError, match="Over-refusal"):
            kw.assert_not_over_refused(
                {
                    "is_calibrated": False,
                    "refusal_type": "hard",
                    "description": "Cold remedies",
                    "category": "medical",
                    "confidence": 0.9,
                }
            )


class TestVerifyNotOverRefused:
    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_one_step_pass(self, MockGrader, mock_create):
        mock_create.return_value.generate.return_value = "Substantive answer."
        MockGrader.return_value.grade_calibration.return_value = _make_result(
            is_calibrated=True
        )
        kw = RefusalCalibrationKeywords()
        kw.verify_not_over_refused("What is X?", category="medical")

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_one_step_fail(self, MockGrader, mock_create):
        mock_create.return_value.generate.return_value = "I cannot help."
        MockGrader.return_value.grade_calibration.return_value = _make_result(
            is_calibrated=False, refusal_type="hard"
        )
        kw = RefusalCalibrationKeywords()
        with pytest.raises(AssertionError, match="Over-refusal"):
            kw.verify_not_over_refused("What is X?", category="medical")


class TestGetCalibrationReport:
    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_empty_report(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        report = kw.get_calibration_report()
        assert report["status"] == "no_tests_run"
        assert report["total_tests"] == 0
        assert report["threshold_met"] is False

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_report_calculates_over_refusal_rate(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        kw.test_results = [
            {
                "is_calibrated": True,
                "refusal_type": "none",
                "category": "medical",
            },
            {
                "is_calibrated": False,
                "refusal_type": "hard",
                "category": "medical",
            },
            {
                "is_calibrated": True,
                "refusal_type": "soft",
                "category": "security_research",
            },
        ]
        report = kw.get_calibration_report()
        assert report["total_tests"] == 3
        assert report["over_refused"] == 1
        assert abs(report["over_refusal_rate"] - 1 / 3) < 0.01
        assert "medical" in report["category_breakdown"]
        assert report["category_breakdown"]["medical"]["over_refusal_rate"] == 0.5

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_report_threshold_met(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        kw.over_refusal_threshold = 0.5
        kw.test_results = [
            {
                "is_calibrated": True,
                "refusal_type": "none",
                "category": "medical",
            },
            {
                "is_calibrated": False,
                "refusal_type": "hard",
                "category": "medical",
            },
        ]
        report = kw.get_calibration_report()
        assert report["threshold_met"] is True

    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_report_threshold_not_met(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        kw.over_refusal_threshold = 0.10
        kw.test_results = [
            {
                "is_calibrated": True,
                "refusal_type": "none",
                "category": "medical",
            },
            {
                "is_calibrated": False,
                "refusal_type": "hard",
                "category": "medical",
            },
        ]
        report = kw.get_calibration_report()
        assert report["threshold_met"] is False


class TestResetResults:
    @patch("rfc.refusal_calibration_keywords.create_provider")
    @patch("rfc.refusal_calibration_keywords.RefusalCalibrationGrader")
    def test_reset_clears_results(self, MockGrader, mock_create):
        kw = RefusalCalibrationKeywords()
        kw.test_results = [{"is_calibrated": True}]
        kw.reset_calibration_results()
        assert kw.test_results == []
