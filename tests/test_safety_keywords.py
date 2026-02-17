"""Tests for rfc.safety_keywords.SafetyKeywords."""

from unittest.mock import MagicMock, patch

from rfc.safety_keywords import SafetyKeywords


class TestSafetyKeywordsInit:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_default_init(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        MockClient.assert_called_once_with(timeout=120, max_retries=2)
        assert kw.safety_threshold == 0.95
        assert kw.test_results == []

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_custom_timeout(self, MockGrader, MockClient):
        SafetyKeywords(timeout=60, max_retries=1)
        MockClient.assert_called_once_with(timeout=60, max_retries=1)


class TestSafetyThreshold:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_set_threshold(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.set_safety_threshold(0.8)
        assert kw.safety_threshold == 0.8

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_set_threshold_string(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.set_safety_threshold("0.9")
        assert kw.safety_threshold == 0.9


class TestSafetyReport:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_empty_report(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        report = kw.get_safety_report()
        assert report["status"] == "no_tests_run"
        assert report["total_tests"] == 0
        assert report["threshold_met"] is False

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_report_with_results(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.test_results = [
            {"is_safe": True, "violation_type": None},
            {"is_safe": True, "violation_type": None},
            {"is_safe": False, "violation_type": "injection"},
        ]
        report = kw.get_safety_report()
        assert report["total_tests"] == 3
        assert report["passed"] == 2
        assert report["failed"] == 1
        assert abs(report["pass_rate"] - 2 / 3) < 0.01

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_report_threshold_met(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.safety_threshold = 0.5
        kw.test_results = [
            {"is_safe": True, "violation_type": None},
            {"is_safe": False, "violation_type": "injection"},
        ]
        report = kw.get_safety_report()
        assert report["threshold_met"] is True

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_report_threshold_not_met(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.safety_threshold = 0.95
        kw.test_results = [
            {"is_safe": True, "violation_type": None},
            {"is_safe": False, "violation_type": "injection"},
        ]
        report = kw.get_safety_report()
        assert report["threshold_met"] is False

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_violation_summary(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.test_results = [
            {"is_safe": False, "violation_type": "injection"},
            {"is_safe": False, "violation_type": "injection"},
            {"is_safe": False, "violation_type": "extraction"},
        ]
        report = kw.get_safety_report()
        assert report["violation_summary"] == {"injection": 2, "extraction": 1}


class TestResetResults:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_reset(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.test_results = [{"is_safe": True}]
        kw.reset_safety_results()
        assert kw.test_results == []


class TestAssertSafetyBoundary:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_safe_result_passes(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        result = {"is_safe": True, "confidence": 0.99}
        kw.assert_safety_boundary(result, "injection")  # should not raise

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_unsafe_result_raises(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        result = {
            "is_safe": False,
            "confidence": 0.3,
            "violation_type": "injection",
            "description": "test prompt",
        }
        try:
            kw.assert_safety_boundary(result, "injection")
            assert False, "Should have raised"
        except Exception as e:
            assert "Safety boundary violated" in str(e)


class TestDetectSystemLeakage:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_no_leakage(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.grader._detect_system_leakage.return_value = False
        assert kw.detect_system_leakage("safe response") is False

    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_leakage_detected(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.grader._detect_system_leakage.return_value = True
        assert kw.detect_system_leakage("leaked system prompt") is True


class TestCheckResponseSafety:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_check_safe_response(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        mock_result = MagicMock()
        mock_result.is_safe = True
        mock_result.confidence = 0.99
        mock_result.violation_type = None
        mock_result.indicators = []
        kw.grader.grade_safety.return_value = mock_result

        result = kw.check_response_safety("prompt", "response")
        assert result["is_safe"] is True
        assert result["confidence"] == 0.99


class TestLogSafetyReport:
    @patch("rfc.safety_keywords.OllamaClient")
    @patch("rfc.safety_keywords.SafetyGrader")
    def test_log_report_no_tests(self, MockGrader, MockClient):
        kw = SafetyKeywords()
        kw.log_safety_report()  # should not raise
