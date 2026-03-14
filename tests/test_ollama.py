"""Tests for rfc.ollama.OllamaClient."""

import os

from unittest.mock import MagicMock, call, patch

import pytest
import requests as req_lib

from rfc.ollama import OllamaClient, LLMClient


class TestOllamaClientInit:
    def test_defaults(self):
        client = OllamaClient()
        assert client.base_url == os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        assert client.model == os.getenv("DEFAULT_MODEL", "phi4:14b")
        assert client.temperature == 0.0
        assert client.max_tokens == 256
        assert client.timeout == 5400
        assert client.max_retries == 2

    @patch.dict(os.environ, {"OLLAMA_ENDPOINT": "http://gpu1:11434"})
    def test_default_base_url_from_env(self):
        client = OllamaClient()
        assert client.base_url == "http://gpu1:11434"

    @patch.dict(os.environ, {"OLLAMA_ENDPOINT": "http://gpu1:11434"})
    def test_explicit_base_url_overrides_env(self):
        client = OllamaClient(base_url="http://myhost:1234")
        assert client.base_url == "http://myhost:1234"

    @patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"})
    def test_default_timeout_from_env(self):
        client = OllamaClient()
        assert client.timeout == 300

    @patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"})
    def test_explicit_timeout_overrides_env(self):
        client = OllamaClient(timeout=60)
        assert client.timeout == 60

    def test_strips_trailing_slash(self):
        client = OllamaClient(base_url="http://example.com/")
        assert client.base_url == "http://example.com"

    @patch.dict(os.environ, {"DEFAULT_MODEL": "llama3"})
    def test_default_model_from_env(self):
        client = OllamaClient()
        assert client.model == "llama3"

    @patch.dict(os.environ, {"DEFAULT_MODEL": "llama3"})
    def test_explicit_model_overrides_env(self):
        client = OllamaClient(model="mistral")
        assert client.model == "mistral"

    def test_negative_temperature(self):
        with pytest.raises(ValueError, match="temperature must be >= 0"):
            OllamaClient(temperature=-0.1)

    def test_zero_max_tokens(self):
        with pytest.raises(ValueError, match="max_tokens must be >= 1"):
            OllamaClient(max_tokens=0)

    def test_custom_timeout(self):
        client = OllamaClient(timeout=300)
        assert client.timeout == 300

    def test_custom_max_retries(self):
        client = OllamaClient(max_retries=5)
        assert client.max_retries == 5

    def test_zero_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout must be >= 1"):
            OllamaClient(timeout=0)

    def test_negative_max_retries_rejected(self):
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            OllamaClient(max_retries=-1)

    def test_zero_max_retries_allowed(self):
        client = OllamaClient(max_retries=0)
        assert client.max_retries == 0


class TestEndpointProperty:
    def test_get_endpoint(self):
        client = OllamaClient(base_url="http://myhost:1234")
        assert client.endpoint == "http://myhost:1234/api/generate"

    def test_set_endpoint_full_url(self):
        client = OllamaClient()
        client.endpoint = "http://newhost:5678/api/generate"
        assert client.base_url == "http://newhost:5678"

    def test_set_endpoint_base_only(self):
        client = OllamaClient()
        client.endpoint = "http://newhost:5678"
        assert client.base_url == "http://newhost:5678"


class TestGenerate:
    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_success(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": " hello world "}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.generate("test prompt")
        assert result == "hello world"

    def test_empty_prompt_rejected(self):
        client = OllamaClient()
        with pytest.raises(ValueError, match="non-empty string"):
            client.generate("")

    def test_non_string_prompt_rejected(self):
        client = OllamaClient()
        with pytest.raises(TypeError, match="prompt must be a str"):
            client.generate(123)

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_http_error(self, mock_post, mock_logger):
        mock_post.side_effect = req_lib.HTTPError("500 Server Error")

        client = OllamaClient()
        with pytest.raises(req_lib.HTTPError):
            client.generate("prompt")


class TestGenerateRetry:
    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.time.sleep")
    @patch("rfc.ollama.requests.post")
    def test_retries_on_read_timeout(self, mock_post, mock_sleep, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "42"}
        mock_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [
            req_lib.exceptions.ReadTimeout("timed out"),
            mock_resp,
        ]

        client = OllamaClient(max_retries=2)
        result = client.generate("What is 6*7?")
        assert result == "42"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.time.sleep")
    @patch("rfc.ollama.requests.post")
    def test_retries_on_connection_error(self, mock_post, mock_sleep, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "ok"}
        mock_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [
            req_lib.exceptions.ConnectionError("refused"),
            mock_resp,
        ]

        client = OllamaClient(max_retries=2)
        result = client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.time.sleep")
    @patch("rfc.ollama.requests.post")
    def test_exhausts_retries_then_raises(self, mock_post, mock_sleep, mock_logger):
        mock_post.side_effect = req_lib.exceptions.ReadTimeout("timed out")

        client = OllamaClient(max_retries=2)
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            client.generate("test")
        # 1 initial + 2 retries = 3 total calls
        assert mock_post.call_count == 3

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.time.sleep")
    @patch("rfc.ollama.requests.post")
    def test_no_retry_on_http_error(self, mock_post, mock_sleep, mock_logger):
        mock_post.side_effect = req_lib.exceptions.HTTPError("500 Server Error")

        client = OllamaClient(max_retries=2)
        with pytest.raises(req_lib.exceptions.HTTPError):
            client.generate("test")
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_no_retry_when_max_retries_zero(self, mock_post, mock_logger):
        mock_post.side_effect = req_lib.exceptions.ReadTimeout("timed out")

        client = OllamaClient(max_retries=0)
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            client.generate("test")
        assert mock_post.call_count == 1

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.time.sleep")
    @patch("rfc.ollama.requests.post")
    def test_exponential_backoff_timing(self, mock_post, mock_sleep, mock_logger):
        mock_post.side_effect = req_lib.exceptions.ReadTimeout("timed out")

        client = OllamaClient(max_retries=2)
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            client.generate("test")

        assert mock_sleep.call_args_list == [call(2), call(4)]


class TestListModels:
    @patch("rfc.ollama.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [
                {"name": "llama3:latest"},
                {"name": "mistral:7b"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = OllamaClient()
        models = client.list_models()
        assert "llama3" in models
        assert "mistral" in models

    @patch("rfc.ollama.requests.get")
    def test_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = OllamaClient()
        assert client.list_models() == []


class TestListModelsDetailed:
    @patch("rfc.ollama.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [
                {
                    "name": "llama3",
                    "size": 4000000000,
                    "modified_at": "2024-01-01",
                    "digest": "abc123456789xyz",
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = OllamaClient()
        models = client.list_models_detailed()
        assert len(models) == 1
        assert models[0]["name"] == "llama3"
        assert len(models[0]["digest"]) == 12  # Truncated to 12 chars


class TestRunningModels:
    @patch("rfc.ollama.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [{"name": "llama3", "size_vram": 1024}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = OllamaClient()
        models = client.running_models()
        assert len(models) == 1

    @patch("rfc.ollama.requests.get")
    def test_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = OllamaClient()
        assert client.running_models() == []


class TestIsBusy:
    @patch("rfc.ollama.requests.get")
    def test_busy(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [{"name": "llama3", "size_vram": 1024}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert OllamaClient().is_busy() is True

    @patch("rfc.ollama.requests.get")
    def test_not_busy(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert OllamaClient().is_busy() is False

    @patch("rfc.ollama.requests.get")
    def test_error_returns_false(self, mock_get):
        mock_get.side_effect = Exception("connection error")
        assert OllamaClient().is_busy() is False


class TestIsAvailable:
    @patch("rfc.ollama.requests.get")
    def test_available(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        assert OllamaClient().is_available() is True

    @patch("rfc.ollama.requests.get")
    def test_unavailable(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        assert OllamaClient().is_available() is False


class TestWaitUntilReady:
    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.get")
    def test_immediate_idle(self, mock_get, mock_logger):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert OllamaClient().wait_until_ready(timeout=5) is True

    def test_invalid_timeout(self):
        with pytest.raises(ValueError, match="timeout must be >= 1"):
            OllamaClient().wait_until_ready(timeout=0)

    def test_invalid_poll_interval(self):
        with pytest.raises(ValueError, match="poll_interval must be >= 1"):
            OllamaClient().wait_until_ready(poll_interval=0)

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.time.sleep")
    @patch("rfc.ollama.time.time")
    @patch("rfc.ollama.requests.get")
    def test_warns_after_one_minute(self, mock_get, mock_time, mock_sleep, mock_logger):
        """Warning includes loaded models and next model after 60s."""
        # Simulate: endpoint available but busy, time advancing past 60s
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        # First few calls: busy (models running), then idle (empty)
        busy_resp = MagicMock()
        busy_resp.status_code = 200
        busy_resp.raise_for_status = MagicMock()
        busy_resp.json.return_value = {"models": [{"name": "phi4:14b"}]}

        idle_resp = MagicMock()
        idle_resp.status_code = 200
        idle_resp.raise_for_status = MagicMock()
        idle_resp.json.return_value = {"models": []}

        # Each loop: GET /api/tags (available check), GET /api/ps (running check)
        mock_get.side_effect = [
            mock_resp,  # loop 1: is_available → 200
            busy_resp,  # loop 1: running_models → busy
            mock_resp,  # loop 2: is_available → 200
            busy_resp,  # loop 2: running_models → busy
            mock_resp,  # loop 3: is_available → 200
            busy_resp,  # loop 3: running_models → busy — triggers warning
            mock_resp,  # loop 4: is_available → 200
            idle_resp,  # loop 4: running_models → idle → done
        ]

        # Time progression: warning triggers when elapsed >= 60
        mock_time.side_effect = [
            0,        # start
            0, 0,     # loop 1: while check, elapsed check
            30, 30,   # loop 2: while check, elapsed check
            61, 61,   # loop 3: while check, elapsed — triggers warning
            65, 65,   # loop 4: while check, elapsed — idle, returns
        ]

        client = OllamaClient(model="gemma3:27b")
        result = client.wait_until_ready(timeout=5400, poll_interval=2)

        assert result is True
        # Verify warn includes loaded models and next model
        warn_calls = [
            str(c) for c in mock_logger.warn.call_args_list
            if "Still waiting for Ollama" in str(c)
        ]
        assert len(warn_calls) >= 1, (
            f"Expected at least one 'Still waiting' warning, got: "
            f"{mock_logger.warn.call_args_list}"
        )
        warn_msg = warn_calls[0]
        assert "phi4:14b" in warn_msg, "Warning should list loaded models"
        assert "gemma3:27b" in warn_msg, "Warning should list next model"


class TestGenerateMetrics:
    """Tests for last_metrics capture from generate() responses."""

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_stores_last_metrics(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "hello",
            "total_duration": 17607688368,
            "load_duration": 108889428,
            "prompt_eval_count": 73,
            "prompt_eval_duration": 489998464,
            "eval_count": 186,
            "eval_duration": 16907870673,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        client.generate("test prompt")

        assert client.last_metrics is not None
        assert client.last_metrics["total_duration_ns"] == 17607688368
        assert client.last_metrics["load_duration_ns"] == 108889428
        assert client.last_metrics["prompt_eval_count"] == 73
        assert client.last_metrics["prompt_eval_duration_ns"] == 489998464
        assert client.last_metrics["eval_count"] == 186
        assert client.last_metrics["eval_duration_ns"] == 16907870673

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_computes_eval_rate(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "hello",
            "eval_count": 186,
            "eval_duration": 16907870673,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        client.generate("test")

        assert client.last_metrics is not None
        # 186 / (16907870673 / 1e9) ≈ 11.00
        assert abs(client.last_metrics["eval_rate"] - 11.00) < 0.1

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_computes_prompt_eval_rate(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "hello",
            "prompt_eval_count": 73,
            "prompt_eval_duration": 489998464,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        client.generate("test")

        assert client.last_metrics is not None
        # 73 / (489998464 / 1e9) ≈ 148.98
        assert abs(client.last_metrics["prompt_eval_rate"] - 148.98) < 0.5

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_missing_metrics_fields_are_none(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "hello"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        client.generate("test")

        assert client.last_metrics is not None
        assert client.last_metrics["total_duration_ns"] is None
        assert client.last_metrics["eval_rate"] is None

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_zero_duration_gives_none_rate(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "hello",
            "eval_count": 10,
            "eval_duration": 0,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        client.generate("test")

        assert client.last_metrics is not None
        assert client.last_metrics["eval_rate"] is None

    def test_last_metrics_none_initially(self):
        client = OllamaClient()
        assert client.last_metrics is None

    @patch("rfc.ollama.logger")
    @patch("rfc.ollama.requests.post")
    def test_last_metrics_includes_model_name(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "hello"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient(model="llama3")
        client.generate("test")

        assert client.last_metrics is not None
        assert client.last_metrics["model_name"] == "llama3"


class TestLLMClientAlias:
    def test_alias(self):
        assert LLMClient is OllamaClient
