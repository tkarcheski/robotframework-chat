"""Tests for CEOKeywords lazy client initialization and provider abstraction.

CEOKeywords must not require API keys at instantiation time so that
Robot Framework ``--dryrun`` can discover keywords without env vars.
The pipeline must use the default LLM provider (via ``LLM_PROVIDER`` env var)
rather than hardcoding any specific backend.
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


class TestCEOProviderAgnostic:
    """CEO pipeline must use the default provider, not hardcode OpenAI."""

    def test_client_uses_default_provider(self) -> None:
        """The client property must not pass provider='openai'."""
        with patch("rfc.ceo_keywords.create_provider") as mock_create:
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") != "openai", (
                "CEO pipeline must not hardcode provider='openai'; "
                "it should use the default from LLM_PROVIDER env var"
            )

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

    def test_grader_uses_default_provider(self) -> None:
        """Grader providers must not hardcode provider='openai'."""
        env = {"CEO_GRADER_MODELS": "model-a,model-b,model-c"}
        with (
            patch.dict("os.environ", env),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            kw._get_multi_grader()

            assert mock_create.call_count == 3
            for call in mock_create.call_args_list:
                call_kwargs = call.kwargs
                assert call_kwargs.get("provider") != "openai", (
                    "Grader providers must not hardcode provider='openai'"
                )

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
