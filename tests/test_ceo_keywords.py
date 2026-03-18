"""Tests for CEOKeywords lazy client initialization and provider selection.

CEOKeywords must not require API keys at instantiation time so that
Robot Framework ``--dryrun`` can discover keywords without env vars.
The pipeline supports a CEO-specific provider override while preserving the
legacy OpenAI behavior for installs that still carry the repo default
``LLM_PROVIDER=ollama`` alongside ``OPENAI_API_KEY``.
"""

from unittest.mock import patch

from rfc.ceo_keywords import CEOKeywords, _DEFAULT_CEO_MAX_TOKENS


class TestCEOKeywordsLazyInit:
    """CEOKeywords should defer provider creation until first use."""

    def test_instantiation_without_provider_keys(self) -> None:
        """CEOKeywords() must succeed even without provider API keys set."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("OPENAI_API_KEY", None)
            # This should NOT raise ValueError
            kw = CEOKeywords()
            assert kw is not None

    def test_client_created_on_first_access(self) -> None:
        """The LLM client should be created lazily when first accessed."""
        with patch("rfc.ceo_keywords.create_provider") as mock_create:
            mock_create.return_value = object()  # dummy provider
            CEOKeywords()
            # create_provider should NOT have been called during __init__
            mock_create.assert_not_called()


class TestCEOProviderSelection:
    """CEO pipeline should support override + backward-compatible fallback."""

    def test_client_uses_ceo_provider_override(self) -> None:
        """CEO_LLM_PROVIDER should take precedence over the global provider."""
        env = {"CEO_LLM_PROVIDER": "openai", "LLM_PROVIDER": "ollama"}
        with (
            patch.dict("os.environ", env),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "openai"

    def test_client_falls_back_to_openai_for_legacy_env(self) -> None:
        """An OpenAI key should preserve the old CEO default when LLM_PROVIDER stays at ollama."""
        env = {"LLM_PROVIDER": "ollama", "OPENAI_API_KEY": "sk-test-key"}
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "openai"

    def test_client_keeps_non_default_global_provider(self) -> None:
        """A non-default LLM_PROVIDER should still drive the CEO pipeline."""
        env = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test-key"}
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "openai"

    def test_client_allows_explicit_ollama_with_openai_key_present(self) -> None:
        """CEO_LLM_PROVIDER=ollama should disable the OpenAI compatibility fallback."""
        env = {
            "CEO_LLM_PROVIDER": "ollama",
            "LLM_PROVIDER": "ollama",
            "OPENAI_API_KEY": "sk-test-key",
        }
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "ollama"

    def test_client_passes_max_tokens(self) -> None:
        """The client property must forward CEO_MAX_TOKENS (default 4096)."""
        with patch("rfc.ceo_keywords.create_provider") as mock_create:
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("max_tokens") == _DEFAULT_CEO_MAX_TOKENS

    def test_max_tokens_from_env(self) -> None:
        """CEO_MAX_TOKENS env var should override the default."""
        env = {"CEO_MAX_TOKENS": "2048"}
        with (
            patch.dict("os.environ", env),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("max_tokens") == 2048

    def test_grader_uses_resolved_provider(self) -> None:
        """Grader providers should use the same resolved provider as the main client."""
        env = {
            "CEO_GRADER_MODELS": "model-a,model-b,model-c",
            "LLM_PROVIDER": "ollama",
            "OPENAI_API_KEY": "sk-test-key",
        }
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            kw._get_multi_grader()

            assert mock_create.call_count == 3
            for call in mock_create.call_args_list:
                call_kwargs = call.kwargs
                assert call_kwargs.get("provider") == "openai"

    def test_grader_passes_max_tokens(self) -> None:
        """Grader providers must receive CEO_MAX_TOKENS."""
        env = {"CEO_GRADER_MODELS": "model-a,model-b,model-c"}
        with (
            patch.dict("os.environ", env),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            kw._get_multi_grader()

            for call in mock_create.call_args_list:
                call_kwargs = call.kwargs
                assert call_kwargs.get("max_tokens") == _DEFAULT_CEO_MAX_TOKENS
