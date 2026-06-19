"""LLM provider abstraction and factory.

Defines the ``LLMProvider`` protocol that all LLM backends must satisfy,
and a ``create_provider()`` factory for instantiation from configuration.
"""

import logging
import os
from typing import Any, Dict, Optional, runtime_checkable

from typing import Protocol

from .ollama import OllamaClient

logger = logging.getLogger(__name__)

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
    response_format: Optional[str]
    last_metrics: Optional[Dict[str, Any]]

    def generate(self, prompt: str) -> str: ...


def create_provider(provider: str = "", **kwargs: Any) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: ``"ollama"``, ``"openai"``, or ``"vllm"``.
                  Defaults to the ``LLM_PROVIDER`` env var, then ``"ollama"``.
                  ``"vllm"`` targets a local vLLM OpenAI-compatible server
                  (``VLLM_BASE_URL``, default ``http://localhost:8000/v1``);
                  vLLM accepts any bearer token, so a dummy key is used.
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
        client: LLMProvider = OllamaClient(**kwargs)
    elif provider == "openai":
        from .openai_client import OpenAIClient

        api_key = kwargs.pop("api_key", "") or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            from .exceptions import MissingProviderConfigError

            raise MissingProviderConfigError(
                provider="openai", variable="OPENAI_API_KEY"
            )
        client = OpenAIClient(api_key=api_key, **kwargs)
    elif provider == "vllm":
        from .openai_client import OpenAIClient

        base_url = kwargs.pop("base_url", "") or os.getenv(
            "VLLM_BASE_URL", "http://localhost:8000/v1"
        )
        # vLLM serves an OpenAI-compatible API and accepts any bearer token;
        # a dummy key satisfies OpenAIClient's non-empty validation.
        api_key = kwargs.pop("api_key", "") or os.getenv("VLLM_API_KEY", "") or "EMPTY"
        client = OpenAIClient(base_url=base_url, api_key=api_key, **kwargs)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            f"Supported: 'ollama', 'openai', 'vllm'."
        )

    return _maybe_wrap_with_graylog(_maybe_wrap_with_cache(client))


def _maybe_wrap_with_graylog(client: LLMProvider) -> LLMProvider:
    """Wrap *client* so each ``generate()`` ships a GELF event to Graylog,
    when ``GRAYLOG_LLM_ENABLED=1`` and the private ``rfc-graylog`` submodule
    is installed.

    Opt-in and best-effort, mirroring :func:`_maybe_wrap_with_cache`: the
    private package is absent from default/public installs, and a missing
    package — or a missing listener/sink at run time — must never block a
    measurement run, so we skip-and-log instead of failing.

    Applied *outermost* (around any caching wrapper): instrumentation should
    observe the fully-wrapped provider's ``generate()``. ``as_ollama`` stays
    correct regardless of wrapper order because ``unwrap_provider`` now peels
    *all* ``__wrapped__`` layers recursively to the concrete client (#83); the
    outermost placement is an instrumentation choice, no longer a load-bearing
    requirement of the single-layer unwrap it once worked around.
    """
    if os.getenv("GRAYLOG_LLM_ENABLED", "") != "1":
        return client

    try:
        from robot_graylog_llm import wrap_provider
    except ImportError:
        logger.warning(
            "GRAYLOG_LLM_ENABLED=1 but the private 'robot_graylog_llm' package "
            "is not installed (run `pip install -e modules/graylog` or "
            "`make robot-graylog`); skipping LLM Graylog instrumentation."
        )
        return client

    return wrap_provider(client)


def _maybe_wrap_with_cache(client: LLMProvider) -> LLMProvider:
    """Wrap *client* in a caching layer when ``ANSWER_CACHE_ENABLED=1`` (#522).

    Opt-in by design: measurement runs leave the cache off so every answer is
    a fresh measurement. When enabled, the wrapper memoizes deterministic
    ``generate()`` calls in Redis and degrades to a passthrough if Redis is
    unreachable — a down cache must never fail a test.
    """
    if os.getenv("ANSWER_CACHE_ENABLED", "") != "1":
        return client

    from .answer_cache import AnswerCache, CachingProvider

    cache = AnswerCache.from_env()
    return CachingProvider(client, cache)


def unwrap_provider(client: Any) -> Any:
    """Return the concrete underlying provider, peeling *every* wrapper layer.

    Provider wrappers (``CachingProvider``, the graylog proxy, and the planned
    nv-cache wrapper) are transparent proxies that expose the wrapped object as
    ``__wrapped__`` (the ``functools.wraps`` convention). Callers that need the
    *concrete* provider type — rather than its structural interface — must
    unwrap first. Non-wrapped clients return themselves (#523).

    Peeling is **recursive**: it walks ``__wrapped__`` down to the base client,
    so any depth of wrapper stack resolves to the concrete provider (#83). This
    is required before nv-cache stacks as a third wrapper at the
    :func:`create_provider` seam (graylog → nv-cache → answer-cache → client) —
    a single-layer peel would stop at the outermost wrapper and hide the
    concrete ``OllamaClient`` from :func:`as_ollama` (RFC-006 §3.2). For 0, 1,
    or 2 wrappers the result is identical to the historical single-peel
    behaviour.
    """
    seen: set[int] = set()
    while hasattr(client, "__wrapped__"):
        # Guard against a pathological self/cyclic ``__wrapped__`` reference so
        # a buggy wrapper can never spin this loop forever.
        if id(client) in seen:
            break
        seen.add(id(client))
        client = client.__wrapped__
    return client


def as_ollama(client: Any) -> Optional[OllamaClient]:
    """Return *client* as an ``OllamaClient`` if it is one (through any cache
    wrapper), else ``None``.

    The Ollama-management keywords (Wait For LLM, Unload Model, Get Running
    Models, LLM Is Busy, Set LLM Endpoint) need the concrete Ollama surface,
    which a transparent proxy cannot satisfy by interface alone. Unwrapping
    at the seam keeps the isinstance check honest and mypy-narrowable (#523).
    """
    inner = unwrap_provider(client)
    return inner if isinstance(inner, OllamaClient) else None


__all__ = [
    "LLMClient",
    "LLMProvider",
    "as_ollama",
    "create_provider",
    "resolve_timeout",
    "unwrap_provider",
]
