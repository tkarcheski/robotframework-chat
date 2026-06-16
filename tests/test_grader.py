"""Tests for rfc.grader.Grader."""

import json
from unittest.mock import MagicMock, patch

import pytest

from rfc.grader import Grader
from rfc.models import GradeResult


class TestGrader:
    def test_init_none_client_rejected(self):
        with pytest.raises(TypeError, match="must not be None"):
            Grader(None)

    def test_init_with_client(self):
        client = MagicMock()
        grader = Grader(client)
        assert grader.llm is client

    def test_grade_correct_answer(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "correct"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "4")
        assert isinstance(result, GradeResult)
        assert result.score == 1.0
        assert isinstance(result.score, float)
        assert result.reason == "correct"

    def test_grade_incorrect_answer(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0, "reason": "wrong"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "5")
        assert result.score == 0.0

    def test_grade_invalid_json(self):
        client = MagicMock()
        client.generate.return_value = "not valid json"
        grader = Grader(client)
        with pytest.raises(ValueError, match="invalid JSON"):
            grader.grade("q", "e", "a")

    def test_grade_missing_score_field(self):
        client = MagicMock()
        client.generate.return_value = '{"reason": "x"}'
        grader = Grader(client)
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade("q", "e", "a")

    def test_grade_missing_reason_field(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1}'
        grader = Grader(client)
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade("q", "e", "a")

    def test_grade_empty_question(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(ValueError, match="non-empty string"):
            grader.grade("", "expected", "actual")

    def test_grade_non_string_input(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(TypeError, match="question must be a str"):
            grader.grade(123, "expected", "actual")

    def test_grade_non_string_expected(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(TypeError, match="expected must be a str"):
            grader.grade("q", 123, "actual")

    def test_grade_partial_score(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.4, "reason": "partially correct"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "It might be 3 or 4")
        assert result.score == 0.4

    def test_grade_prompt_requests_fractional_scores(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "partial"}'
        grader = Grader(client)
        grader.grade("q", "e", "a")
        prompt = client.generate.call_args[0][0]
        assert "score must be a number between 0.0 and 1.0" in prompt
        assert "use partial credit" in prompt
        assert '"score": 0.0 to 1.0' in prompt


class TestGraderLlmMetricsEmission:
    """Grader.grade() emits RFC_DATA:llm_metrics so DbListener sees token counts (#611)."""

    @patch("rfc.rfc_data.logger")
    def test_emits_llm_metrics_when_last_metrics_available(
        self, mock_logger: MagicMock
    ) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "correct"}'
        client.last_metrics = {"eval_count": 42, "prompt_eval_count": 100}
        grader = Grader(client)
        grader.grade("q", "e", "a")
        # At least one logger.info call must contain RFC_DATA:llm_metrics
        calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("RFC_DATA:llm_metrics" in c for c in calls)

    @patch("rfc.rfc_data.logger")
    def test_emitted_payload_contains_token_counts(
        self, mock_logger: MagicMock
    ) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "partial"}'
        client.last_metrics = {"eval_count": 77, "prompt_eval_count": 200}
        grader = Grader(client)
        grader.grade("What is 2+2?", "4", "maybe 4")
        calls = [str(c) for c in mock_logger.info.call_args_list]
        metrics_calls = [c for c in calls if "RFC_DATA:llm_metrics" in c]
        assert metrics_calls
        payload = json.loads(metrics_calls[0].split("RFC_DATA:llm_metrics:")[1].rstrip("'\"(),"))
        assert payload["eval_count"] == 77
        assert payload["prompt_eval_count"] == 200

    @patch("rfc.rfc_data.logger")
    def test_no_emit_when_last_metrics_is_none(
        self, mock_logger: MagicMock
    ) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "ok"}'
        client.last_metrics = None
        grader = Grader(client)
        grader.grade("q", "e", "a")
        calls = [str(c) for c in mock_logger.info.call_args_list]
        assert not any("RFC_DATA:llm_metrics" in c for c in calls)
