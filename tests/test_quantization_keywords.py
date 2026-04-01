"""Tests for rfc.quantization_keywords.QuantizationKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.quantization_keywords import QuantizationKeywords


class TestQuantizationKeywordsInit:
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_default_init(self, MockGrader, mock_create):
        QuantizationKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_custom_timeout(self, MockGrader, mock_create):
        QuantizationKeywords(timeout=120, max_retries=1)
        mock_create.assert_called_once_with(timeout=120, max_retries=1)


class TestDiscoverQuantizationVariants:
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_finds_q4_and_q8(self, MockGrader, mock_create):
        kw = QuantizationKeywords()
        kw.client.list_models_detailed = MagicMock(
            return_value=[
                {"name": "mistral:7b-instruct-q4_K_M", "size": 4_000_000_000},
                {"name": "mistral:7b-instruct-q8_0", "size": 8_000_000_000},
                {"name": "llama3:latest", "size": 5_000_000_000},
            ]
        )
        result = kw.discover_quantization_variants("mistral")
        assert result["base_model"] == "mistral"
        assert result["q4_model"] == "mistral:7b-instruct-q4_K_M"
        assert result["q8_model"] == "mistral:7b-instruct-q8_0"
        assert result["both_available"] is True

    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_missing_q8(self, MockGrader, mock_create):
        kw = QuantizationKeywords()
        kw.client.list_models_detailed = MagicMock(
            return_value=[
                {"name": "mistral:7b-instruct-q4_K_M", "size": 4_000_000_000},
            ]
        )
        result = kw.discover_quantization_variants("mistral")
        assert result["q4_model"] == "mistral:7b-instruct-q4_K_M"
        assert result["q8_model"] is None
        assert result["both_available"] is False

    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_no_variants_found(self, MockGrader, mock_create):
        kw = QuantizationKeywords()
        kw.client.list_models_detailed = MagicMock(
            return_value=[
                {"name": "llama3:latest", "size": 5_000_000_000},
            ]
        )
        result = kw.discover_quantization_variants("mistral")
        assert result["q4_model"] is None
        assert result["q8_model"] is None
        assert result["both_available"] is False

    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_case_insensitive_match(self, MockGrader, mock_create):
        kw = QuantizationKeywords()
        kw.client.list_models_detailed = MagicMock(
            return_value=[
                {"name": "Mistral:7b-Q4_K_M", "size": 4_000_000_000},
                {"name": "Mistral:7b-Q8_0", "size": 8_000_000_000},
            ]
        )
        result = kw.discover_quantization_variants("mistral")
        assert result["q4_model"] is not None
        assert result["q8_model"] is not None


class TestRunQuantizationComparison:
    @patch("rfc.quantization_keywords.emit_rfc_data")
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_returns_correct_structure(self, MockGrader, mock_create, mock_emit):
        kw = QuantizationKeywords()
        kw.client.generate.return_value = "42"
        mock_grade = MagicMock()
        mock_grade.score = 1.0
        mock_grade.reason = "Correct"
        kw.grader.grade.return_value = mock_grade

        prompts = [
            {"question": "What is 6*7?", "expected": "42"},
        ]
        result = kw.run_quantization_comparison(
            q4_model="model:q4", q8_model="model:q8", prompts=prompts
        )
        assert "q4_scores" in result
        assert "q8_scores" in result
        assert "q4_avg" in result
        assert "q8_avg" in result
        assert "delta" in result
        assert "degradation_pct" in result
        assert "prompt_details" in result

    @patch("rfc.quantization_keywords.emit_rfc_data")
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_model_switching(self, MockGrader, mock_create, mock_emit):
        kw = QuantizationKeywords()
        # Use a real string for model so attribute assignment works
        kw.client.model = "original"
        kw.client.generate.return_value = "answer"
        mock_grade = MagicMock()
        mock_grade.score = 0.8
        mock_grade.reason = "ok"
        kw.grader.grade.return_value = mock_grade

        prompts = [{"question": "Q1", "expected": "A1"}]
        kw.run_quantization_comparison("model:q4", "model:q8", prompts)

        # Model should be restored to original after comparison
        assert kw.client.model == "original"

    @patch("rfc.quantization_keywords.emit_rfc_data")
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_degradation_calculation(self, MockGrader, mock_create, mock_emit):
        kw = QuantizationKeywords()
        kw.client.generate.return_value = "answer"

        # Q4 gets 0.5, Q8 gets 1.0 → 50% degradation
        scores = iter([
            MagicMock(score=0.5, reason="partial"),   # Q4
            MagicMock(score=1.0, reason="correct"),    # Q8
        ])
        kw.grader.grade.side_effect = lambda *a, **k: next(scores)

        prompts = [{"question": "Q", "expected": "A"}]
        result = kw.run_quantization_comparison("m:q4", "m:q8", prompts)
        assert result["q4_avg"] == 0.5
        assert result["q8_avg"] == 1.0
        assert result["delta"] == pytest.approx(-0.5)
        assert result["degradation_pct"] == pytest.approx(50.0)

    @patch("rfc.quantization_keywords.emit_rfc_data")
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_emits_rfc_data(self, MockGrader, mock_create, mock_emit):
        kw = QuantizationKeywords()
        kw.client.generate.return_value = "42"
        mock_grade = MagicMock()
        mock_grade.score = 1.0
        mock_grade.reason = "ok"
        kw.grader.grade.return_value = mock_grade

        prompts = [{"question": "Q", "expected": "A"}]
        kw.run_quantization_comparison("m:q4", "m:q8", prompts)

        emitted_keys = [c.args[0] for c in mock_emit.call_args_list]
        assert "score" in emitted_keys
        assert "grading_reason" in emitted_keys
        assert "quant_delta" in emitted_keys
        assert "quant_degradation_pct" in emitted_keys


class TestAssertAcceptableDegradation:
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_passes_within_threshold(self, MockGrader, mock_create):
        kw = QuantizationKeywords()
        result = {"degradation_pct": 10.0, "q4_avg": 0.9, "q8_avg": 1.0}
        kw.assert_acceptable_degradation(result, max_degradation_pct=20.0)

    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_raises_when_exceeds_threshold(self, MockGrader, mock_create):
        kw = QuantizationKeywords()
        result = {"degradation_pct": 30.0, "q4_avg": 0.7, "q8_avg": 1.0}
        with pytest.raises(AssertionError, match="Quantization degradation"):
            kw.assert_acceptable_degradation(result, max_degradation_pct=20.0)

    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_default_threshold(self, MockGrader, mock_create):
        kw = QuantizationKeywords()
        result = {"degradation_pct": 25.0, "q4_avg": 0.75, "q8_avg": 1.0}
        with pytest.raises(AssertionError):
            kw.assert_acceptable_degradation(result)


class TestLogQuantizationDelta:
    @patch("rfc.quantization_keywords.emit_rfc_data")
    @patch("rfc.quantization_keywords.create_provider")
    @patch("rfc.quantization_keywords.Grader")
    def test_emits_delta_data(self, MockGrader, mock_create, mock_emit):
        kw = QuantizationKeywords()
        result = {
            "q4_avg": 0.8,
            "q8_avg": 1.0,
            "delta": -0.2,
            "degradation_pct": 20.0,
            "q4_model": "m:q4",
            "q8_model": "m:q8",
        }
        kw.log_quantization_delta(result)
        emitted_keys = [c.args[0] for c in mock_emit.call_args_list]
        assert "quant_q4_avg" in emitted_keys
        assert "quant_q8_avg" in emitted_keys
        assert "quant_delta" in emitted_keys
        assert "quant_degradation_pct" in emitted_keys
