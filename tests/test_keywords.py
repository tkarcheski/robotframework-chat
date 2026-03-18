"""Tests for rfc.keywords.LLMKeywords."""

import json
import os
from unittest.mock import MagicMock, patch

from rfc.keywords import LLMKeywords
from rfc.ollama import OllamaClient


class TestLLMKeywordsInit:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_default_init(self, MockGrader, mock_create):
        LLMKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_custom_timeout_and_retries(self, MockGrader, mock_create):
        LLMKeywords(timeout=60, max_retries=5)
        mock_create.assert_called_once_with(timeout=60, max_retries=5)

    @patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"})
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_default_timeout_from_env(self, MockGrader, mock_create):
        LLMKeywords()
        mock_create.assert_called_once_with(timeout=300, max_retries=2)


class TestLLMKeywordsSetters:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_endpoint_ollama(self, MockGrader, mock_create):
        """When provider is OllamaClient, sets endpoint property."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        kw.set_llm_endpoint("http://custom:11434")
        assert kw.client.endpoint == "http://custom:11434"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_endpoint_non_ollama(self, MockGrader, mock_create):
        """When provider is non-Ollama, sets base_url."""
        kw = LLMKeywords()
        kw.set_llm_endpoint("https://api.openai.com/v1")
        assert kw.client.base_url == "https://api.openai.com/v1"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_model(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.set_llm_model("mistral")
        assert kw.client.model == "mistral"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_parameters(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.set_llm_parameters(temperature=0.7, max_tokens=512)
        assert kw.client.temperature == 0.7
        assert kw.client.max_tokens == 512


class TestLLMKeywordsAsk:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        result = kw.ask_llm("What is 6 * 7?")
        kw.client.generate.assert_called_once_with("What is 6 * 7?")
        assert result == "42"

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_emits_llm_metrics(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = {
            "model_name": "llama3",
            "total_duration_ns": 17607688368,
            "eval_rate": 11.0,
        }

        kw.ask_llm("What is 6 * 7?")

        # RFC_DATA messages must be emitted at INFO level so the
        # DbListener.log_message() receives them at the default --loglevel.
        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        metrics_calls = [c for c in info_calls if "RFC_DATA:llm_metrics:" in c]
        assert len(metrics_calls) == 1

        # Parse and verify the JSON payload
        raw = [
            c.args[0]
            for c in mock_rfc_logger.info.call_args_list
            if "RFC_DATA:llm_metrics:" in str(c)
        ][0]
        payload = raw.split("RFC_DATA:llm_metrics:", 1)[1]
        data = json.loads(payload)
        assert data["model_name"] == "llama3"
        assert data["total_duration_ns"] == 17607688368
        assert data["prompt_text"] == "What is 6 * 7?"

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_skips_metrics_when_none(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None

        kw.ask_llm("test")

        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        metrics_calls = [c for c in info_calls if "RFC_DATA:llm_metrics:" in c]
        assert len(metrics_calls) == 0


class TestLLMKeywordsAskThinking:
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_strips_thinking(self, MockGrader, mock_create, mock_logger):
        kw = LLMKeywords()
        kw.client.generate.return_value = (
            "<think>reasoning here</think>The answer is 42."
        )
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        result = kw.ask_llm("What is 6 * 7?")
        assert result == "The answer is 42."

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_emits_thinking_data(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "<think>step by step</think>42"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        kw.ask_llm("test")

        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        thinking_calls = [c for c in info_calls if "RFC_DATA:thinking_text:" in c]
        assert len(thinking_calls) == 1
        assert "step by step" in thinking_calls[0]

        token_calls = [c for c in info_calls if "RFC_DATA:thinking_tokens:" in c]
        assert len(token_calls) == 1

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_no_thinking_no_data(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        kw.ask_llm("test")

        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        thinking_calls = [c for c in info_calls if "RFC_DATA:thinking_text:" in c]
        assert len(thinking_calls) == 0


class TestLLMKeywordsSetParametersExtended:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_extended_parameters(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.set_llm_parameters(
            temperature=0.7,
            max_tokens=512,
            seed=42,
            top_p=0.9,
            top_k=40,
            num_ctx=4096,
            keep_alive="5m",
        )
        assert kw.client.temperature == 0.7
        assert kw.client.max_tokens == 512
        assert kw.client.seed == 42
        assert kw.client.top_p == 0.9
        assert kw.client.top_k == 40
        assert kw.client.num_ctx == 4096
        assert kw.client.keep_alive == "5m"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_parameters_string_coercion(self, MockGrader, mock_create):
        """Robot Framework passes all args as strings."""
        kw = LLMKeywords()
        kw.set_llm_parameters(
            temperature="0.5",
            max_tokens="1024",
            seed="42",
            top_p="0.9",
            top_k="40",
            num_ctx="8192",
        )
        assert kw.client.seed == 42
        assert kw.client.num_ctx == 8192


class TestLLMKeywordsUnload:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_unload_model_ollama(self, MockGrader, mock_create):
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.unload_model.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        result = kw.unload_model()
        assert result is True
        mock_client.unload_model.assert_called_once_with(None)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_unload_model_non_ollama_returns_false(self, MockGrader, mock_create):
        kw = LLMKeywords()
        result = kw.unload_model()
        assert result is False


class TestLLMKeywordsGrade:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_grade_answer(self, MockGrader, mock_create):
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
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_with_ollama(self, MockGrader, mock_create):
        """When the provider is OllamaClient, delegates to wait_until_ready."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.wait_until_ready.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        result = kw.wait_for_llm(timeout=60, poll_interval=5)
        assert result is True
        mock_client.wait_until_ready.assert_called_once_with(60, 5)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_string_args(self, MockGrader, mock_create):
        """Robot Framework passes all args as strings."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.wait_until_ready.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        kw.wait_for_llm(timeout="30", poll_interval="3")
        mock_client.wait_until_ready.assert_called_once_with(30, 3)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_non_ollama_returns_true(self, MockGrader, mock_create):
        """Non-Ollama providers skip wait and return True."""
        kw = LLMKeywords()
        # mock_create returns a MagicMock (not OllamaClient spec)
        result = kw.wait_for_llm()
        assert result is True


class TestLLMKeywordsRunningModels:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_get_running_models_with_ollama(self, MockGrader, mock_create):
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.running_models.return_value = [{"name": "llama3"}]
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        result = kw.get_running_models()
        assert result == [{"name": "llama3"}]

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_get_running_models_non_ollama_returns_empty(self, MockGrader, mock_create):
        kw = LLMKeywords()
        result = kw.get_running_models()
        assert result == []

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_with_ollama(self, MockGrader, mock_create):
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.is_busy.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        assert kw.llm_is_busy() is True

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_non_ollama_returns_false(self, MockGrader, mock_create):
        kw = LLMKeywords()
        assert kw.llm_is_busy() is False
