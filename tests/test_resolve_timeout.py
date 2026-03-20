"""Tests for the resolve_timeout helper in llm_client."""

import os
from unittest.mock import patch

from rfc.llm_client import resolve_timeout


class TestResolveTimeout:
    """Tests for resolve_timeout()."""

    def test_default_returns_5400(self) -> None:
        """No argument and no env var → default 5400."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_TIMEOUT", None)
            assert resolve_timeout() == 5400

    def test_explicit_timeout_overrides_default(self) -> None:
        """Explicit timeout beats the default."""
        assert resolve_timeout(60) == 60

    def test_env_var_overrides_default(self) -> None:
        """OLLAMA_TIMEOUT env var overrides the default when no arg given."""
        with patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"}):
            assert resolve_timeout() == 300

    def test_explicit_timeout_beats_env_var(self) -> None:
        """Explicit timeout takes precedence over env var."""
        with patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"}):
            assert resolve_timeout(60) == 60

    def test_string_timeout_converted_to_int(self) -> None:
        """Robot Framework passes strings; they must be converted."""
        assert resolve_timeout("120") == 120  # type: ignore[arg-type]
