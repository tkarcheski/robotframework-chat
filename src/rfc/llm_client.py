"""LLM provider abstraction and factory.

Defines the ``LLMProvider`` protocol that all LLM backends must satisfy,
and a ``create_provider()`` factory for instantiation from configuration.
"""

import os
from typing import Any, Dict, Optional, runtime_checkable

from typing import Protocol

from .ollama import OllamaClient

# Backward-compatible alias
LLMClient = OllamaClient

_DEFAULT_TIMEOUT = 5400


def resolve_timeout(timeout: int | None = None) -> int:
    """Resolve the LLM request timeout.

    Precedence: explicit *timeout* arg > ``OLLAMA_TIMEOUT`` env var > 5400s default.
    """
    if timeout is not None:
        return int(timeout)
    return int(os.getenv("OLLAMA_TIMEOUT", str(_DEFAULT_TIMEOUT)))


@runtime_checkable
class LLMProvider(Protocol):
    """Structural protocol that every LLM backend must satisfy."""

    model: str
    temperature: float
    max_tokens: int
    seed: Optional[int]
    top_p: Optional[float]
    top_k: Optional[int]
    num_ctx: Optional[int]
    keep_alive: Optional[str]
    last_metrics: Optional[Dict[str, Any]]

    def generate(self, prompt: str) -> str: ...


def create_provider(provider: str = "", **kwargs: Any) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: ``"ollama"`` or ``"openai"``.
                  Defaults to the ``LLM_PROVIDER`` env var, then ``"ollama"``.
        **kwargs: Forwarded to the provider constructor
                  (e.g. ``timeout``, ``max_retries``).

    Returns:
        An object satisfying :class:`LLMProvider`.

    Raises:
        ValueError: If the provider name is unknown or required config is missing.
    """
    if not provider:
        provider = os.getenv("LLM_PROVIDER", "ollama")

    provider = provider.lower().strip()

    if provider == "ollama":
        return OllamaClient(**kwargs)

    if provider == "openai":
        from .openai_client import OpenAIClient

        api_key = kwargs.pop("api_key", "") or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            from .exceptions import MissingProviderConfigError

            raise MissingProviderConfigError(
                provider="openai", variable="OPENAI_API_KEY"
            )
        return OpenAIClient(api_key=api_key, **kwargs)

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. Supported: 'ollama', 'openai'."
    )


__all__ = ["LLMClient", "LLMProvider", "create_provider", "resolve_timeout"]
