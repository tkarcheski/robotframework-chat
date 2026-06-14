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
# Finite Redis timeouts (seconds): a down cache must degrade fast, not hang.
DEFAULT_CONNECT_TIMEOUT = 1.0
DEFAULT_SOCKET_TIMEOUT = 1.0
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
        # Once Redis fails, disable the cache for the rest of the run so we
        # don't burn the socket timeout on every subsequent get/set (#523).
        self._disabled = False

    @classmethod
    def from_env(cls) -> "AnswerCache":
        """Build a cache from ``REDIS_URL`` / ``ANSWER_CACHE_*`` env vars.

        Finite socket timeouts are mandatory: redis-py defaults to blocking
        sockets with no timeout, so an unresponsive host would hang the first
        lookup forever and defeat the documented passthrough behaviour (#523).
        """
        import redis

        url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
        ttl = int(os.getenv("ANSWER_CACHE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
        version = os.getenv("ANSWER_CACHE_VERSION", DEFAULT_VERSION)
        connect_timeout = float(
            os.getenv("ANSWER_CACHE_CONNECT_TIMEOUT", str(DEFAULT_CONNECT_TIMEOUT))
        )
        socket_timeout = float(
            os.getenv("ANSWER_CACHE_SOCKET_TIMEOUT", str(DEFAULT_SOCKET_TIMEOUT))
        )
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
        )
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
        if self._disabled:
            return None
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
        if self._disabled:
            return
        try:
            self._redis.set(key, answer, ex=self._ttl)
        except _redis_connection_errors() as exc:
            self._note_unreachable(exc)

    def _note_unreachable(self, exc: BaseException) -> None:
        # Disable for the rest of the run so we never pay the timeout twice.
        self._disabled = True
        if not self._logged_unreachable:
            logger.warning(
                "Answer cache unreachable (%s); bypassing cache for this run.",
                exc,
            )
            self._logged_unreachable = True


def _cache_hit_metrics(model: Optional[str]) -> Dict[str, Any]:
    """Honest zero-cost metrics for a cache hit.

    Mirrors the key set of ``rfc.ollama._extract_metrics`` /
    ``rfc.openai_client._extract_metrics`` so a hit row is schema-identical
    to a miss row. Counts are 0 (a hit did no model work) and rates are
    ``None`` (division undefined) — never values inherited from a prior
    fresh generation (#523).
    """
    return {
        "model_name": model,
        "cache_hit": True,
        "total_duration_ns": 0,
        "load_duration_ns": 0,
        "prompt_eval_count": 0,
        "prompt_eval_duration_ns": 0,
        "prompt_eval_rate": None,
        "eval_count": 0,
        "eval_duration_ns": 0,
        "eval_rate": None,
    }


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
        # Standard wrapper accessor (functools.wraps convention) so callers
        # that need the concrete underlying type — e.g. the OllamaClient
        # isinstance gates in keywords.py — can unwrap the proxy (#523).
        object.__setattr__(self, "__wrapped__", client)

    def unwrap(self) -> _CacheableClient:
        """Return the wrapped client (peels exactly one cache layer)."""
        return self._client

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

        A hit performs zero model work, so its metrics must report zero —
        never inherit the token counts / durations of the prior fresh call
        (which would fabricate usage and wrongly drain token budgets, #523).
        The synthesized dict mirrors ``_extract_metrics``'s key set so a hit
        row has the same schema as a miss row.
        """
        client.last_metrics = _cache_hit_metrics(getattr(client, "model", None))

    # ── Transparent proxying ────────────────────────────────────────────

    @property  # type: ignore[misc]
    def __class__(self) -> type:
        # Delegate the virtual class to the wrapped client so that
        # isinstance(caching_provider, OllamaClient) returns True (#531).
        # Python's isinstance() checks obj.__class__ when type(obj) does not
        # match — this satisfies the PEP 3119 virtual-subclassing path without
        # altering type() or the MRO.
        return type(self._client)

    def __getattr__(self, name: str) -> Any:
        # __getattr__ only fires for names not found normally, so this never
        # shadows generate / _client / _cache.
        return getattr(self._client, name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Writes go to the wrapped client so param setters mutate the real
        # provider (our own attrs are set via object.__setattr__ in __init__).
        setattr(self._client, name, value)


__all__ = ["AnswerCache", "CachingProvider", "is_deterministic"]
