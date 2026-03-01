"""Tests for rfc.keywords.LLMKeywords."""

import json
import os
from unittest.mock import MagicMock, patch

from rfc.keywords import LLMKeywords


class TestLLMKeywordsInit:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_default_init(self, MockGrader, MockClient):
        LLMKeywords()
        MockClient.assert_called_once_with(timeout=120, max_retries=2)
        MockGrader.assert_called_once_with(MockClient.return_value)

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_custom_timeout_and_retries(self, MockGrader, MockClient):
        LLMKeywords(timeout=60, max_retries=5)
        MockClient.assert_called_once_with(timeout=60, max_retries=5)

    @patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"})
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_default_timeout_from_env(self, MockGrader, MockClient):
        LLMKeywords()
        MockClient.assert_called_once_with(timeout=300, max_retries=2)


class TestLLMKeywordsSetters:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_set_endpoint(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.set_llm_endpoint("http://custom:11434")
        assert kw.client.endpoint == "http://custom:11434"

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_set_model(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.set_llm_model("mistral")
        assert kw.client.model == "mistral"

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_set_parameters(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.set_llm_parameters(temperature=0.7, max_tokens=512)
        assert kw.client.temperature == 0.7
        assert kw.client.max_tokens == 512


class TestLLMKeywordsAsk:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_ask_llm(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        result = kw.ask_llm("What is 6 * 7?")
        kw.client.generate.assert_called_once_with("What is 6 * 7?")
        assert result == "42"

    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_emits_ollama_metrics(self, MockGrader, MockClient, mock_logger):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = {
            "model_name": "llama3",
            "total_duration_ns": 17607688368,
            "eval_rate": 11.0,
        }

        kw.ask_llm("What is 6 * 7?")

        # RFC_DATA messages must be emitted at INFO level so the
        # DbListener.log_message() receives them at the default --loglevel.
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        metrics_calls = [c for c in info_calls if "RFC_DATA:ollama_metrics:" in c]
        assert len(metrics_calls) == 1

        # Parse and verify the JSON payload
        raw = [
            c.args[0]
            for c in mock_logger.info.call_args_list
            if "RFC_DATA:ollama_metrics:" in str(c)
        ][0]
        payload = raw.split("RFC_DATA:ollama_metrics:", 1)[1]
        data = json.loads(payload)
        assert data["model_name"] == "llama3"
        assert data["total_duration_ns"] == 17607688368
        assert data["prompt_text"] == "What is 6 * 7?"

    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_skips_metrics_when_none(self, MockGrader, MockClient, mock_logger):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None

        kw.ask_llm("test")

        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        metrics_calls = [c for c in info_calls if "RFC_DATA:ollama_metrics:" in c]
        assert len(metrics_calls) == 0


class TestLLMKeywordsGrade:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_grade_answer(self, MockGrader, MockClient):
        kw = LLMKeywords()
        mock_result = MagicMock()
        mock_result.score = 1
        mock_result.reason = "correct"
        kw.grader.grade.return_value = mock_result

        score, reason = kw.grade_answer("Q", "expected", "actual")
        assert score == 1
        assert reason == "correct"
        kw.grader.grade.assert_called_once_with("Q", "expected", "actual")


class TestLLMKeywordsWait:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.wait_until_ready.return_value = True
        result = kw.wait_for_llm(timeout=60, poll_interval=5)
        assert result is True
        kw.client.wait_until_ready.assert_called_once_with(60, 5)

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_string_args(self, MockGrader, MockClient):
        """Robot Framework passes all args as strings."""
        kw = LLMKeywords()
        kw.client.wait_until_ready.return_value = True
        kw.wait_for_llm(timeout="30", poll_interval="3")
        kw.client.wait_until_ready.assert_called_once_with(30, 3)


class TestLLMKeywordsRunningModels:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_get_running_models(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.running_models.return_value = [{"name": "llama3"}]
        result = kw.get_running_models()
        assert result == [{"name": "llama3"}]

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_true(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.is_busy.return_value = True
        assert kw.llm_is_busy() is True

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_false(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.is_busy.return_value = False
        assert kw.llm_is_busy() is False
