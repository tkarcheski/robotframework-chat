"""Tests for rfc.openai_client.OpenAIClient."""

import os
from unittest.mock import MagicMock, call, patch

import pytest
import requests as req_lib

from rfc.openai_client import OpenAIClient, _extract_metrics


class TestOpenAIClientInit:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_defaults(self):
        client = OpenAIClient()
        assert client.base_url == "https://api.openai.com/v1"
        assert client.api_key == "sk-test"
        assert client.model == os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
        assert client.temperature == 0.0
        assert client.max_tokens == 256
        assert client.timeout == 5400
        assert client.max_retries == 2

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "OPENAI_TIMEOUT": "300"})
    def test_default_timeout_from_env(self):
        client = OpenAIClient()
        assert client.timeout == 300

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "OPENAI_TIMEOUT": "300"})
    def test_explicit_timeout_overrides_env(self):
        client = OpenAIClient(timeout=60)
        assert client.timeout == 60

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_strips_trailing_slash(self):
        client = OpenAIClient(base_url="https://api.example.com/v1/")
        assert client.base_url == "https://api.example.com/v1"

    def test_empty_api_key_raises(self):
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="api_key must be a non-empty"):
                OpenAIClient()

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_empty_model_falls_back_to_default(self):
        """When model='', falls back to DEFAULT_MODEL env var or gpt-4o-mini."""
        client = OpenAIClient(model="")
        assert client.model == os.getenv("DEFAULT_MODEL", "gpt-4o-mini")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_negative_temperature(self):
        with pytest.raises(ValueError, match="temperature must be >= 0"):
            OpenAIClient(temperature=-0.1)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_zero_max_tokens(self):
        with pytest.raises(ValueError, match="max_tokens must be >= 1"):
            OpenAIClient(max_tokens=0)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_zero_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout must be >= 1"):
            OpenAIClient(timeout=0)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_negative_max_retries_rejected(self):
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            OpenAIClient(max_retries=-1)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_zero_max_retries_allowed(self):
        client = OpenAIClient(max_retries=0)
        assert client.max_retries == 0

    def test_custom_base_url(self):
        client = OpenAIClient(base_url="https://api.together.xyz/v1", api_key="sk-test")
        assert client.base_url == "https://api.together.xyz/v1"

    @patch.dict(
        os.environ, {"OPENAI_API_KEY": "sk-env", "OPENAI_BASE_URL": "https://custom/v1"}
    )
    def test_base_url_from_env(self):
        client = OpenAIClient()
        assert client.base_url == "https://custom/v1"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"})
    def test_explicit_api_key_overrides_env(self):
        client = OpenAIClient(api_key="sk-explicit")
        assert client.api_key == "sk-explicit"


class TestGenerate:
    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_success(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": " hello world "}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OpenAIClient(api_key="sk-test")
        result = client.generate("test prompt")
        assert result == "hello world"

        # Verify correct endpoint called
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.openai.com/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
        assert kwargs["json"]["messages"] == [
            {"role": "user", "content": "test prompt"}
        ]

    def test_empty_prompt_rejected(self):
        client = OpenAIClient(api_key="sk-test")
        with pytest.raises(ValueError, match="non-empty string"):
            client.generate("")

    def test_non_string_prompt_rejected(self):
        client = OpenAIClient(api_key="sk-test")
        with pytest.raises(TypeError, match="prompt must be a str"):
            client.generate(123)  # type: ignore[arg-type]

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_http_error(self, mock_post, mock_logger):
        mock_post.side_effect = req_lib.HTTPError("401 Unauthorized")

        client = OpenAIClient(api_key="sk-test")
        with pytest.raises(req_lib.HTTPError):
            client.generate("prompt")


class TestGenerateRetry:
    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.time.sleep")
    @patch("rfc.openai_client.requests.post")
    def test_retries_on_read_timeout(self, mock_post, mock_sleep, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "42"}}],
            "usage": {},
        }
        mock_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [
            req_lib.exceptions.ReadTimeout("timed out"),
            mock_resp,
        ]

        client = OpenAIClient(api_key="sk-test", max_retries=2)
        result = client.generate("What is 6*7?")
        assert result == "42"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.time.sleep")
    @patch("rfc.openai_client.requests.post")
    def test_retries_on_connection_error(self, mock_post, mock_sleep, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        mock_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [
            req_lib.exceptions.ConnectionError("refused"),
            mock_resp,
        ]

        client = OpenAIClient(api_key="sk-test", max_retries=2)
        result = client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.time.sleep")
    @patch("rfc.openai_client.requests.post")
    def test_exhausts_retries_then_raises(self, mock_post, mock_sleep, mock_logger):
        mock_post.side_effect = req_lib.exceptions.ReadTimeout("timed out")

        client = OpenAIClient(api_key="sk-test", max_retries=2)
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            client.generate("test")
        assert mock_post.call_count == 3

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.time.sleep")
    @patch("rfc.openai_client.requests.post")
    def test_no_retry_on_http_error(self, mock_post, mock_sleep, mock_logger):
        mock_post.side_effect = req_lib.exceptions.HTTPError("401 Unauthorized")

        client = OpenAIClient(api_key="sk-test", max_retries=2)
        with pytest.raises(req_lib.exceptions.HTTPError):
            client.generate("test")
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_no_retry_when_max_retries_zero(self, mock_post, mock_logger):
        mock_post.side_effect = req_lib.exceptions.ReadTimeout("timed out")

        client = OpenAIClient(api_key="sk-test", max_retries=0)
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            client.generate("test")
        assert mock_post.call_count == 1

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.time.sleep")
    @patch("rfc.openai_client.requests.post")
    def test_exponential_backoff_timing(self, mock_post, mock_sleep, mock_logger):
        mock_post.side_effect = req_lib.exceptions.ReadTimeout("timed out")

        client = OpenAIClient(api_key="sk-test", max_retries=2)
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            client.generate("test")

        assert mock_sleep.call_args_list == [call(2), call(4)]


class TestMetrics:
    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_stores_last_metrics(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OpenAIClient(api_key="sk-test")
        client.generate("test")

        assert client.last_metrics is not None
        assert client.last_metrics["prompt_tokens"] == 10
        assert client.last_metrics["completion_tokens"] == 5
        assert client.last_metrics["total_tokens"] == 15

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_missing_usage_fields(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OpenAIClient(api_key="sk-test")
        client.generate("test")

        assert client.last_metrics is not None
        assert client.last_metrics["prompt_tokens"] is None
        assert client.last_metrics["completion_tokens"] is None
        assert client.last_metrics["total_tokens"] is None

    def test_last_metrics_none_initially(self):
        client = OpenAIClient(api_key="sk-test")
        assert client.last_metrics is None

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_stores_reasoning_tokens_in_last_metrics(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 80,
                "total_tokens": 130,
                "completion_tokens_details": {
                    "reasoning_tokens": 60,
                    "accepted_prediction_tokens": 0,
                    "rejected_prediction_tokens": 0,
                },
                "prompt_tokens_details": {
                    "cached_tokens": 20,
                },
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OpenAIClient(api_key="sk-test")
        client.generate("test")

        assert client.last_metrics is not None
        assert client.last_metrics["reasoning_tokens"] == 60
        assert client.last_metrics["cached_tokens"] == 20
        assert client.last_metrics["prompt_eval_count"] == 50
        assert client.last_metrics["eval_count"] == 80

    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_last_metrics_includes_model_name(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        client.generate("test")

        assert client.last_metrics is not None
        assert client.last_metrics["model_name"] == "gpt-4o"


class TestExtractMetrics:
    def test_full_usage(self):
        data = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            }
        }
        metrics = _extract_metrics(data, "gpt-4o")
        assert metrics["model_name"] == "gpt-4o"
        assert metrics["prompt_tokens"] == 10
        assert metrics["completion_tokens"] == 20
        assert metrics["total_tokens"] == 30

    def test_no_usage(self):
        metrics = _extract_metrics({}, "gpt-4o")
        assert metrics["model_name"] == "gpt-4o"
        assert metrics["prompt_tokens"] is None

    def test_extracts_reasoning_tokens(self):
        data = {
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 80,
                "total_tokens": 130,
                "completion_tokens_details": {
                    "reasoning_tokens": 60,
                },
            }
        }
        metrics = _extract_metrics(data, "o3")
        assert metrics["reasoning_tokens"] == 60

    def test_extracts_cached_tokens(self):
        data = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {
                    "cached_tokens": 80,
                },
            }
        }
        metrics = _extract_metrics(data, "gpt-4o")
        assert metrics["cached_tokens"] == 80

    def test_extracts_prediction_tokens(self):
        data = {
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 40,
                "total_tokens": 90,
                "completion_tokens_details": {
                    "reasoning_tokens": 0,
                    "accepted_prediction_tokens": 15,
                    "rejected_prediction_tokens": 5,
                },
            }
        }
        metrics = _extract_metrics(data, "gpt-4o")
        assert metrics["accepted_prediction_tokens"] == 15
        assert metrics["rejected_prediction_tokens"] == 5

    def test_maps_to_ollama_equivalents(self):
        data = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            }
        }
        metrics = _extract_metrics(data, "gpt-4o")
        assert metrics["prompt_eval_count"] == 10
        assert metrics["eval_count"] == 20

    def test_missing_details_defaults_to_none(self):
        data = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        }
        metrics = _extract_metrics(data, "gpt-4o")
        assert metrics["reasoning_tokens"] is None
        assert metrics["cached_tokens"] is None
        assert metrics["accepted_prediction_tokens"] is None
        assert metrics["rejected_prediction_tokens"] is None

    def test_null_details_defaults_to_none(self):
        """When details objects are explicitly null in JSON."""
        data = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "prompt_tokens_details": None,
                "completion_tokens_details": None,
            }
        }
        metrics = _extract_metrics(data, "gpt-4o")
        assert metrics["reasoning_tokens"] is None
        assert metrics["cached_tokens"] is None


class TestProtocolCompliance:
    def test_satisfies_llm_provider(self):
        from rfc.llm_client import LLMProvider

        client = OpenAIClient(api_key="sk-test")
        assert isinstance(client, LLMProvider)


# ── Validation edge cases (lines 45, 52) ────────────────────────────


class TestOpenAIClientValidationEdgeCases:
    def test_non_string_base_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="base_url must be a non-empty string"):
            OpenAIClient(base_url=123, api_key="sk-test")  # type: ignore[arg-type]

    def test_non_string_model_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEFAULT_MODEL", raising=False)
        with pytest.raises(ValueError, match="model must be a non-empty string"):
            OpenAIClient(model=123, api_key="sk-test")  # type: ignore[arg-type]


# ── Optional params in payload (lines 100, 102, 104) ────────────────


class TestOpenAIClientOptionalParams:
    @patch("rfc.openai_client.logger")
    @patch("rfc.openai_client.requests.post")
    def test_seed_top_p_top_k_in_payload(self, mock_post, mock_logger):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OpenAIClient(api_key="sk-test", seed=42, top_p=0.9, top_k=40)
        client.generate("test")

        payload = mock_post.call_args[1]["json"]
        assert payload["seed"] == 42
        assert payload["top_p"] == 0.9
        assert payload["top_k"] == 40
