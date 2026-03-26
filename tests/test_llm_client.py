"""Tests for rfc.llm_client — LLMProvider protocol and create_provider factory."""

import os
from unittest.mock import patch

import pytest

from rfc.llm_client import LLMClient, LLMProvider, create_provider
from rfc.ollama import OllamaClient


class TestLLMProviderProtocol:
    def test_ollama_client_satisfies_protocol(self):
        """OllamaClient structurally satisfies LLMProvider."""
        client = OllamaClient()
        assert isinstance(client, LLMProvider)

    def test_protocol_requires_generate(self):
        """Objects without generate() do not satisfy LLMProvider."""

        class Bad:
            model = "x"
            last_metrics = None

        assert not isinstance(Bad(), LLMProvider)

    def test_protocol_requires_model(self):
        """Objects without model attribute do not satisfy LLMProvider."""

        class Bad:
            last_metrics = None

            def generate(self, prompt: str) -> str:
                return ""

        assert not isinstance(Bad(), LLMProvider)


class TestCreateProvider:
    @patch.dict(os.environ, {}, clear=False)
    def test_default_returns_ollama(self):
        """With no LLM_PROVIDER set, defaults to OllamaClient."""
        env = os.environ.copy()
        env.pop("LLM_PROVIDER", None)
        with patch.dict(os.environ, env, clear=True):
            client = create_provider()
            assert isinstance(client, OllamaClient)

    @patch.dict(os.environ, {"LLM_PROVIDER": "ollama"})
    def test_explicit_ollama(self):
        client = create_provider()
        assert isinstance(client, OllamaClient)

    @patch.dict(
        os.environ,
        {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test-key"},
    )
    def test_openai_provider(self):
        from rfc.openai_client import OpenAIClient

        client = create_provider()
        assert isinstance(client, OpenAIClient)

    @patch.dict(os.environ, {"LLM_PROVIDER": "openai"})
    def test_openai_without_api_key_raises(self):
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            # Ensure LLM_PROVIDER is still set
            os.environ["LLM_PROVIDER"] = "openai"
            from rfc.exceptions import MissingProviderConfigError

            with pytest.raises(MissingProviderConfigError, match="OPENAI_API_KEY"):
                create_provider()

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_provider(provider="unknown_provider")

    def test_explicit_provider_arg_overrides_env(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}):
            client = create_provider(provider="ollama")
            assert isinstance(client, OllamaClient)

    def test_kwargs_forwarded_to_ollama(self):
        client = create_provider(provider="ollama", timeout=60, max_retries=5)
        assert isinstance(client, OllamaClient)
        assert client.timeout == 60
        assert client.max_retries == 5

    @patch.dict(
        os.environ,
        {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
    )
    def test_kwargs_forwarded_to_openai(self):
        from rfc.openai_client import OpenAIClient

        client = create_provider(timeout=30, max_retries=3)
        assert isinstance(client, OpenAIClient)
        assert client.timeout == 30
        assert client.max_retries == 3


class TestLLMClientAlias:
    def test_backward_compatible_alias(self):
        """LLMClient is still available for backward compatibility."""
        assert LLMClient is OllamaClient
