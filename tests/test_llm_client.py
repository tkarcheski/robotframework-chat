"""Tests for rfc.llm_client — LLMProvider protocol and create_provider factory."""

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from rfc.llm_client import (
    LLMClient,
    LLMProvider,
    _maybe_wrap_with_graylog,
    as_ollama,
    create_provider,
    unwrap_provider,
)
from rfc.ollama import OllamaClient


class TestLLMProviderProtocol:
    def test_ollama_client_satisfies_protocol(self):
        """OllamaClient structurally satisfies LLMProvider."""
        client = OllamaClient(model="test-model")
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
            client = create_provider(model="test-model")
            assert isinstance(client, OllamaClient)

    @patch.dict(os.environ, {"LLM_PROVIDER": "ollama"})
    def test_explicit_ollama(self):
        client = create_provider(model="test-model")
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
            client = create_provider(provider="ollama", model="test-model")
            assert isinstance(client, OllamaClient)

    def test_kwargs_forwarded_to_ollama(self):
        client = create_provider(
            provider="ollama", model="test-model", timeout=60, max_retries=5
        )
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


class TestCreateProviderWithCache:
    """Tests for create_provider() when ANSWER_CACHE_ENABLED=1 (#531)."""

    @patch("rfc.answer_cache.AnswerCache.from_env")
    @patch.dict(os.environ, {"ANSWER_CACHE_ENABLED": "1"})
    def test_isinstance_transparent_when_cache_enabled(
        self, mock_from_env: MagicMock
    ) -> None:
        """CachingProvider.__class__ must delegate to the inner type so that
        isinstance(create_provider(), OllamaClient) is True even with caching
        enabled (#531).
        """
        mock_from_env.return_value = MagicMock()
        client = create_provider(provider="ollama", model="test-model")
        assert isinstance(client, OllamaClient)

    @patch("rfc.answer_cache.AnswerCache.from_env")
    @patch.dict(os.environ, {"ANSWER_CACHE_ENABLED": "1"})
    def test_type_still_caching_provider_when_cache_enabled(
        self, mock_from_env: MagicMock
    ) -> None:
        """type() returns CachingProvider — __class__ is a virtual delegation only."""
        from rfc.answer_cache import CachingProvider

        mock_from_env.return_value = MagicMock()
        client = create_provider(provider="ollama", model="test-model")
        assert type(client) is CachingProvider

    @patch("rfc.answer_cache.AnswerCache.from_env")
    @patch.dict(os.environ, {"ANSWER_CACHE_ENABLED": "1", "OPENAI_API_KEY": "sk-test"})
    def test_openai_isinstance_transparent_when_cache_enabled(
        self, mock_from_env: MagicMock
    ) -> None:
        """isinstance(create_provider('openai'), OpenAIClient) is True with cache."""
        from rfc.openai_client import OpenAIClient

        mock_from_env.return_value = MagicMock()
        client = create_provider(provider="openai")
        assert isinstance(client, OpenAIClient)


def _fake_graylog_module() -> types.ModuleType:
    """A stand-in for the private ``robot_graylog_llm`` submodule.

    ``wrap_provider`` mirrors the real one: a transparent proxy exposing
    ``__wrapped__`` so ``unwrap_provider`` can recover the inner client.
    """

    class _FakeGraylogProvider:
        def __init__(self, inner: object) -> None:
            self.__wrapped__ = inner

        def __getattr__(self, name: str) -> object:
            return getattr(self.__wrapped__, name)

    mod = types.ModuleType("robot_graylog_llm")
    mod.wrap_provider = lambda client: _FakeGraylogProvider(client)  # type: ignore[attr-defined]
    mod._FakeGraylogProvider = _FakeGraylogProvider  # type: ignore[attr-defined]
    return mod


class TestCreateProviderWithGraylog:
    """Tests for opt-in Graylog provider wrapping (GRAYLOG_LLM_ENABLED=1)."""

    def test_disabled_returns_client_unchanged(self) -> None:
        """Flag off → the client is returned untouched (no wrapping)."""
        env = os.environ.copy()
        env.pop("GRAYLOG_LLM_ENABLED", None)
        with patch.dict(os.environ, env, clear=True):
            client = OllamaClient(model="test-model")
            assert _maybe_wrap_with_graylog(client) is client

    def test_enabled_but_package_missing_returns_client_unchanged(self) -> None:
        """Flag on but the private submodule is not installed → skip-and-log."""
        with patch.dict(os.environ, {"GRAYLOG_LLM_ENABLED": "1"}):
            with patch.dict(sys.modules, {"robot_graylog_llm": None}):
                client = OllamaClient(model="test-model")
                assert _maybe_wrap_with_graylog(client) is client

    def test_enabled_with_package_wraps_and_stays_unwrappable(self) -> None:
        """Flag on + package present → wrapped, and unwrap recovers the inner."""
        fake = _fake_graylog_module()
        with patch.dict(os.environ, {"GRAYLOG_LLM_ENABLED": "1"}):
            with patch.dict(sys.modules, {"robot_graylog_llm": fake}):
                client = OllamaClient(model="test-model")
                wrapped = _maybe_wrap_with_graylog(client)
                assert wrapped is not client
                assert isinstance(wrapped, fake._FakeGraylogProvider)
                assert unwrap_provider(wrapped) is client

    def test_create_provider_wraps_outermost_so_as_ollama_still_works(self) -> None:
        """create_provider() applies graylog outermost; as_ollama unwraps it."""
        from rfc.llm_client import as_ollama

        fake = _fake_graylog_module()
        env = os.environ.copy()
        env.pop("ANSWER_CACHE_ENABLED", None)
        env["GRAYLOG_LLM_ENABLED"] = "1"
        with patch.dict(os.environ, env, clear=True):
            with patch.dict(sys.modules, {"robot_graylog_llm": fake}):
                client = create_provider(provider="ollama", model="test-model")
                assert isinstance(client, fake._FakeGraylogProvider)
                assert isinstance(as_ollama(client), OllamaClient)


class _FakeWrapper:
    """A minimal transparent proxy exposing ``__wrapped__`` (functools.wraps
    convention), used to stack arbitrary wrapper depth over a base client.

    Mirrors the contract every real provider wrapper honours
    (``CachingProvider``, the graylog proxy, and the planned nv-cache wrapper):
    expose the inner object as ``__wrapped__`` and proxy everything else.
    """

    def __init__(self, inner: object) -> None:
        self.__wrapped__ = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self.__wrapped__, name)


class TestUnwrapProviderRecursive:
    """unwrap_provider / as_ollama must peel *all* __wrapped__ layers (#83).

    RFC-006 (§3.2, PR #82) makes recursive unwrap a hard prerequisite for
    stacking nv-cache as a *third* wrapper at the create_provider seam
    (graylog → nv-cache → answer-cache → OllamaClient). A single-layer peel
    stops at the outermost wrapper and hides the concrete client.
    """

    def test_unwrap_zero_wrappers_returns_self(self) -> None:
        """0 wrappers: a bare client unwraps to itself (no __wrapped__)."""
        base = OllamaClient(model="test-model")
        assert unwrap_provider(base) is base

    def test_unwrap_single_wrapper_reaches_base(self) -> None:
        """1 wrapper: peeled to the base (the historical single-peel case)."""
        base = OllamaClient(model="test-model")
        wrapped = _FakeWrapper(base)
        assert unwrap_provider(wrapped) is base

    def test_unwrap_two_wrappers_reaches_base(self) -> None:
        """2 wrappers (cache + graylog today): both peeled to the base."""
        base = OllamaClient(model="test-model")
        wrapped = _FakeWrapper(_FakeWrapper(base))
        assert unwrap_provider(wrapped) is base

    def test_unwrap_three_wrappers_reaches_base(self) -> None:
        """3 wrappers (nv-cache + cache + graylog): peeled to the base.

        This is the case that fails under a single-layer unwrap.
        """
        base = OllamaClient(model="test-model")
        wrapped = _FakeWrapper(_FakeWrapper(_FakeWrapper(base)))
        assert unwrap_provider(wrapped) is base

    def test_as_ollama_resolves_through_three_wrappers(self) -> None:
        """as_ollama recovers the concrete OllamaClient through a 3-deep stack."""
        base = OllamaClient(model="test-model")
        wrapped = _FakeWrapper(_FakeWrapper(_FakeWrapper(base)))
        assert as_ollama(wrapped) is base

    def test_as_ollama_none_when_base_is_not_ollama_through_stack(self) -> None:
        """A non-Ollama base under any depth of wrappers yields None."""

        class _NotOllama:
            model = "x"

        base = _NotOllama()
        wrapped = _FakeWrapper(_FakeWrapper(_FakeWrapper(base)))
        assert as_ollama(wrapped) is None

    def test_unwrap_through_nested_caching_providers(self) -> None:
        """Real CachingProvider nesting (the nv-cache-over-answer-cache shape)
        unwraps to the concrete OllamaClient, and as_ollama still resolves.
        """
        from rfc.answer_cache import CachingProvider

        base = OllamaClient(model="test-model")
        inner = CachingProvider(base, MagicMock())
        outer = CachingProvider(inner, MagicMock())
        assert unwrap_provider(outer) is base
        assert as_ollama(outer) is base

    def test_graylog_over_two_caches_as_ollama_resolves(self) -> None:
        """graylog → CachingProvider → CachingProvider → OllamaClient: the full
        three-wrapper stack at the seam still resolves to the concrete client.
        """
        from rfc.answer_cache import CachingProvider

        fake = _fake_graylog_module()
        base = OllamaClient(model="test-model")
        stacked = fake._FakeGraylogProvider(
            CachingProvider(CachingProvider(base, MagicMock()), MagicMock())
        )
        assert unwrap_provider(stacked) is base
        assert as_ollama(stacked) is base


class TestLLMClientAlias:
    def test_backward_compatible_alias(self):
        """LLMClient is still available for backward compatibility."""
        assert LLMClient is OllamaClient
