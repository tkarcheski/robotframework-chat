"""Redis-backed answer cache for ``client.generate()`` (issue #522).

Memoizes identical LLM requests — same provider type, model, endpoint, prompt
and output-affecting parameters — so a re-run of an unchanged suite against an
unchanged model serves the stored answer at ~0 compute instead of re-hitting
the LLM.

This is a **measurement harness**, so correctness beats convenience:

* **Opt-in.** Wired in only when ``ANSWER_CACHE_ENABLED=1`` (see
  :func:`rfc.llm_client.create_provider`). Grading / measurement runs leave it
  off.
* **Deterministic-only by default.** Even when enabled, a request is cached
  only if it is reproducible: ``temperature == 0`` OR a ``seed`` is set.
  Non-deterministic requests legitimately differ per call and are skipped
  unless ``ANSWER_CACHE_NONDETERMINISTIC=1``.
* **Provenance-recorded.** On a cache hit the served answer's ``last_metrics``
  carries ``cache_hit=True`` so result rows are honest about being replayed.
* **Never fails a request.** If Redis is unreachable, the cache logs once and
  degrades to a passthrough — a down cache must never fail a test.

The cache key is the SHA-256 of a canonical JSON document over every attribute
that affects model output, plus a version namespace so the whole cache can be
busted on a schema change. Omitting any output-affecting attribute would
silently serve wrong answers, so the key builder enumerates them explicitly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

# Defaults mirror the documented env vars (see .env.example).
DEFAULT_REDIS_URL = "redis://localhost:6379/1"  # db 1, NOT Superset's db 0
DEFAULT_TTL_SECONDS = 604800  # 7 days
DEFAULT_VERSION = "v1"
_KEY_PREFIX = "rfc:answer_cache"

# Attributes that affect model output and therefore the cache key. Missing any
# of these would let two genuinely different requests collide on one key.
_KEY_ATTRS = (
    "model",
    "base_url",
    "temperature",
    "max_tokens",
    "seed",
    "top_p",
    "top_k",
    "num_ctx",
    "response_format",
)


class _CacheableClient(Protocol):
    """The subset of an LLM client the cache reads to build a key."""

    model: str
    temperature: float
    max_tokens: int
    seed: Optional[int]
    top_p: Optional[float]
    top_k: Optional[int]
    num_ctx: Optional[int]
    response_format: Optional[str]
    last_metrics: Optional[Dict[str, Any]]

    def generate(self, prompt: str) -> str: ...


def _redis_connection_errors() -> tuple[type[BaseException], ...]:
    """Return the redis exception types that mean "cache is unreachable".

    Imported lazily so importing this module never hard-requires ``redis``
    being importable at module load (it is a declared dependency, but the
    lazy import keeps the failure mode local and testable).
    """
    try:
        import redis

        return (redis.RedisError, OSError)
    except Exception:  # pragma: no cover - redis always installed in practice
        return (OSError,)


class AnswerCache:
    """Stores and retrieves LLM answers keyed by their full request signature."""

    def __init__(
        self,
        redis_client: Any,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        version: str = DEFAULT_VERSION,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._version = version
        # Latch so we log a Redis outage once per process, not per call.
        self._logged_unreachable = False

    @classmethod
    def from_env(cls) -> "AnswerCache":
        """Build a cache from ``REDIS_URL`` / ``ANSWER_CACHE_*`` env vars."""
        import redis

        url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
        ttl = int(os.getenv("ANSWER_CACHE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
        version = os.getenv("ANSWER_CACHE_VERSION", DEFAULT_VERSION)
        client = redis.Redis.from_url(url, decode_responses=True)
        return cls(redis_client=client, ttl_seconds=ttl, version=version)

    def make_key(self, client: _CacheableClient, prompt: str) -> str:
        """Return the cache key for *client*'s current params and *prompt*.

        The key is ``rfc:answer_cache:<version>:<sha256>`` where the digest is
        taken over a canonical JSON document of the provider type and every
        output-affecting attribute. Canonical JSON (sorted keys, no spaces)
        makes the digest stable across processes and dict orderings.
        """
        payload: Dict[str, Any] = {
            "version": self._version,
            "provider_type": type(client).__name__,
            "prompt": prompt,
        }
        for attr in _KEY_ATTRS:
            payload[attr] = getattr(client, attr, None)

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{_KEY_PREFIX}:{self._version}:{digest}"

    def get(self, key: str) -> Optional[str]:
        """Return the cached answer for *key*, or ``None`` on miss / outage."""
        try:
            value = self._redis.get(key)
        except _redis_connection_errors() as exc:
            self._note_unreachable(exc)
            return None
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    def set(self, key: str, answer: str) -> None:
        """Store *answer* under *key* with the configured TTL (best-effort)."""
        try:
            self._redis.set(key, answer, ex=self._ttl)
        except _redis_connection_errors() as exc:
            self._note_unreachable(exc)

    def _note_unreachable(self, exc: BaseException) -> None:
        if not self._logged_unreachable:
            logger.warning(
                "Answer cache unreachable (%s); bypassing cache for this run.",
                exc,
            )
            self._logged_unreachable = True


def is_deterministic(client: _CacheableClient) -> bool:
    """True if *client*'s current params make its output reproducible.

    Reproducible means ``temperature == 0`` or a ``seed`` is set; only such
    requests are safe to memoize without the cache changing what a run
    measures.
    """
    temperature = getattr(client, "temperature", 0.0)
    seed = getattr(client, "seed", None)
    return temperature == 0 or seed is not None


class CachingProvider:
    """Transparent caching wrapper around any LLM client with ``generate()``.

    Proxies all attribute access (reads and writes) to the wrapped client so
    keyword setters like *Set LLM Model* / *Set LLM Parameters* keep working,
    while intercepting :meth:`generate` to serve memoized answers.
    """

    def __init__(
        self,
        client: _CacheableClient,
        cache: AnswerCache,
        cache_nondeterministic: Optional[bool] = None,
    ) -> None:
        if cache_nondeterministic is None:
            cache_nondeterministic = (
                os.getenv("ANSWER_CACHE_NONDETERMINISTIC", "") == "1"
            )
        # Bypass __setattr__ proxying for our own private attributes.
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_cache", cache)
        object.__setattr__(
            self, "_cache_nondeterministic", bool(cache_nondeterministic)
        )

    def generate(self, prompt: str) -> str:
        client = self._client

        cacheable = self._cache_nondeterministic or is_deterministic(client)
        if not cacheable:
            return client.generate(prompt)

        key = self._cache.make_key(client, prompt)

        cached = self._cache.get(key)
        if cached is not None:
            self._record_hit(client)
            return cached

        answer = client.generate(prompt)
        self._cache.set(key, answer)
        return answer

    def _record_hit(self, client: _CacheableClient) -> None:
        """Mark the replayed answer as a cache hit in ``last_metrics``.

        A hit produces no fresh model metrics, so we synthesize a minimal
        metrics dict carrying ``cache_hit=True`` — honest provenance that the
        keyword layer surfaces into the results schema.
        """
        metrics = dict(client.last_metrics or {})
        metrics["cache_hit"] = True
        client.last_metrics = metrics

    # ── Transparent proxying ────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        # __getattr__ only fires for names not found normally, so this never
        # shadows generate / _client / _cache.
        return getattr(self._client, name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Writes go to the wrapped client so param setters mutate the real
        # provider (our own attrs are set via object.__setattr__ in __init__).
        setattr(self._client, name, value)


__all__ = ["AnswerCache", "CachingProvider", "is_deterministic"]
