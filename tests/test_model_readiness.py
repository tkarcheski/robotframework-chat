"""Tests for provider-aware readiness checks (online + model-loaded).

A run-local-models pass against a fleet should *skip* (not fail) a (model,
suite) cell when the provider endpoint is offline or the target model cannot
be loaded in time, so empty-response cold-loads no longer record false-positive
test failures. These tests cover the readiness surface on each provider and the
``Ensure Model Ready`` keyword that suites call in their Suite Setup.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from rfc.exceptions import (
    ModelNotReadyError,
    ProviderOfflineError,
    RFCSkipError,
)
from rfc.keywords import LLMKeywords
from rfc.llm_client import create_provider
from rfc.ollama import OllamaClient
from rfc.openai_client import OpenAIClient


def _keywords_with_client(client: object) -> LLMKeywords:
    """Build LLMKeywords without touching the network, then swap in *client*."""
    with patch("rfc.keywords.create_provider", return_value=MagicMock()):
        kw = LLMKeywords()
    kw.client = client  # type: ignore[assignment]
    return kw


class TestOllamaEnsureReady:
    def _client(self) -> OllamaClient:
        return OllamaClient(model="llama3", base_url="http://host:11434")

    def test_offline_raises_provider_offline(self) -> None:
        client = self._client()
        with patch.object(client, "is_available", return_value=False):
            with pytest.raises(ProviderOfflineError):
                client.ensure_ready(timeout=5)

    def test_empty_warmup_raises_model_not_ready(self) -> None:
        client = self._client()
        with (
            patch.object(client, "is_available", return_value=True),
            patch.object(client, "wait_until_ready", return_value=True),
            patch.object(client, "generate", return_value="   "),
        ):
            with pytest.raises(ModelNotReadyError):
                client.ensure_ready(timeout=5)

    def test_happy_path_loads_model(self) -> None:
        client = self._client()
        with (
            patch.object(client, "is_available", return_value=True),
            patch.object(client, "wait_until_ready", return_value=True) as ready,
            patch.object(client, "generate", return_value="pong") as gen,
        ):
            client.ensure_ready(timeout=5)
        ready.assert_called_once()
        gen.assert_called_once()  # warm-up actually loads the model

    def test_skips_warmup_when_disabled(self) -> None:
        client = self._client()
        with (
            patch.object(client, "is_available", return_value=True),
            patch.object(client, "wait_until_ready", return_value=True),
            patch.object(client, "generate") as gen,
        ):
            client.ensure_ready(timeout=5, warmup=False)
        gen.assert_not_called()

    def test_skip_errors_are_robot_skip(self) -> None:
        # Both readiness failures inherit the ROBOT_SKIP_EXECUTION marker.
        assert issubclass(ProviderOfflineError, RFCSkipError)
        assert issubclass(ModelNotReadyError, RFCSkipError)
        assert ProviderOfflineError.ROBOT_SKIP_EXECUTION is True
        assert ModelNotReadyError.ROBOT_SKIP_EXECUTION is True


class TestOpenAIIsOnline:
    def _client(self) -> OpenAIClient:
        return OpenAIClient(base_url="http://vllm:8000/v1", api_key="EMPTY", model="m")

    @patch("rfc.openai_client.requests.get")
    def test_online_when_models_returns_200(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200)
        assert self._client().is_online() is True
        # Probes the OpenAI-compatible /models catalog (works for vLLM too).
        assert mock_get.call_args.args[0] == "http://vllm:8000/v1/models"

    @patch("rfc.openai_client.requests.get")
    def test_offline_when_non_200(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=503)
        assert self._client().is_online() is False

    @patch("rfc.openai_client.requests.get")
    def test_offline_when_connection_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = req_lib.ConnectionError("refused")
        assert self._client().is_online() is False


class TestOpenAIEnsureReady:
    def _client(self) -> OpenAIClient:
        return OpenAIClient(base_url="http://vllm:8000/v1", api_key="EMPTY", model="m")

    def test_offline_raises_provider_offline(self) -> None:
        client = self._client()
        with patch.object(client, "is_online", return_value=False):
            with pytest.raises(ProviderOfflineError):
                client.ensure_ready(timeout=5)

    def test_online_does_not_warm_up_by_default(self) -> None:
        # vLLM / OpenAI servers load the model at startup; the /models probe
        # is sufficient, so we don't spend a request warming up by default.
        client = self._client()
        with (
            patch.object(client, "is_online", return_value=True),
            patch.object(client, "generate") as gen,
        ):
            client.ensure_ready(timeout=5)
        gen.assert_not_called()


class TestCreateProviderVllm:
    def test_vllm_uses_openai_client_with_vllm_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VLLM_BASE_URL", "http://rig:8000/v1")
        monkeypatch.delenv("ANSWER_CACHE_ENABLED", raising=False)
        client = create_provider("vllm", model="qwen")
        assert isinstance(client, OpenAIClient)
        assert client.base_url == "http://rig:8000/v1"
        # vLLM accepts any bearer; a dummy key keeps OpenAIClient validation happy.
        assert client.api_key == "EMPTY"

    def test_unknown_provider_message_lists_vllm(self) -> None:
        with pytest.raises(ValueError, match="vllm"):
            create_provider("nope")


class TestEnsureModelReadyKeyword:
    def test_delegates_to_provider_ensure_ready(self) -> None:
        client = MagicMock()
        kw = _keywords_with_client(client)
        kw.ensure_model_ready(timeout=42)
        client.ensure_ready.assert_called_once_with(timeout=42)

    def test_fallback_warmup_empty_raises_skip(self) -> None:
        # A provider without ensure_ready falls back to a warm-up generate;
        # an empty response skips (not fails) the suite.
        class _Bare:
            model = "x"
            base_url = "http://h"

            def generate(self, prompt: str) -> str:
                return ""

        kw = _keywords_with_client(_Bare())
        with pytest.raises(ModelNotReadyError):
            kw.ensure_model_ready()

    def test_fallback_warmup_ok_passes(self) -> None:
        class _Bare:
            model = "x"
            base_url = "http://h"

            def generate(self, prompt: str) -> str:
                return "pong"

        kw = _keywords_with_client(_Bare())
        kw.ensure_model_ready()  # no raise
