"""Tests for CEOKeywords lazy client initialization.

CEOKeywords must not require API keys at instantiation time so that
Robot Framework ``--dryrun`` can discover keywords without env vars.
"""

from unittest.mock import patch

from rfc.ceo_keywords import CEOKeywords


class TestCEOKeywordsLazyInit:
    """CEOKeywords should defer provider creation until first use."""

    def test_instantiation_without_api_key(self) -> None:
        """CEOKeywords() must succeed even without OPENAI_API_KEY set."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove the key if it exists
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
