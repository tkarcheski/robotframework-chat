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
* **Never fails a request** *in a live-on-miss mode.* If Redis is unreachable,
  the cache logs once and degrades to a passthrough — a down cache must never
  fail a ``record_and_replay`` test.
* **Replay modes** (RFC-010 S2, #259). :class:`CachingProvider` takes an explicit
  :class:`CacheMode` — ``record_and_replay`` (default, live+store on miss),
  ``exact_only`` (exact-digest-only, no semantic reuse), or ``cache_only`` (never
  call upstream; a miss or an unreachable cache is a LOUD :class:`AnswerCacheMiss`,
  the CI zero-token guarantee). ``cache_only`` deliberately does *not* passthrough
  on outage: silently going live would break its zero-token contract.

The cache key is the SHA-256 of a canonical JSON document over every attribute
that affects model output, plus a version namespace so the whole cache can be
busted on a schema change. Omitting any output-affecting attribute would
silently serve wrong answers, so the key builder enumerates them explicitly.
When the client can resolve its model **digest** (Ollama, via ``/api/tags``),
that digest is folded in too (#526): an Ollama tag can be repointed in place, so
keying on the tag name alone would replay answers from the old weights under the
new tag. Providers whose model id already pins the weights (OpenAI snapshot ids,
vLLM per-process weights) lack the resolver and simply omit the digest field.

RFC-010 S4 (#262) adds two invalidation affordances on top of that key. A suite
whose prompt embeds repo state (a code snapshot, the current commit, a versioned
prompt) may set ``client.cache_context`` to a fingerprint of that state; it is
folded into the key so a code change invalidates its own cached answers instead
of silently replaying an answer about the old code. And :meth:`AnswerCache.invalidate`
plus ``rfc cache invalidate`` bust the cache by scope — one version namespace or
the whole keyspace — without hand-editing Redis, reusing the version namespace as
the same bust lever a deliberate ``v2->v3`` schema bump uses.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

# Defaults mirror the documented env vars (see .env.example).
DEFAULT_REDIS_URL = "redis://localhost:6379/1"  # db 1, NOT Superset's db 0
DEFAULT_TTL_SECONDS = 604800  # 7 days
# v2 (issue #526): the key now includes the resolved model *digest*, not just
# the tag name, so an Ollama tag repointed in place is a miss instead of a stale
# hit. Bumping v1→v2 is a deliberate cache-wide invalidation — every entry
# written under v1 (tag-only keys) is orphaned and re-generated once. BREAKING
# for any persisted cache.
DEFAULT_VERSION = "v2"
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
    # `think` changes what the model emits (reasoning on/off/level), so it must
    # be part of the key (#131). Adding it self-busts pre-existing entries whose
    # payload lacked the field — acceptable given the 7-day TTL.
    "think",
)


class CacheMode(enum.Enum):
    """Replay mode for :class:`CachingProvider` (RFC-010 S2, #259; scopes #19).

    An explicit, per-run switch over what a cache *miss* means. The load-bearing
    honesty rule (RFC-010 §3): a stale or missing entry must fail explicitly —
    never silently pass, never silently go live.

    * ``RECORD_AND_REPLAY`` (default) — serve on an exact hit; on a miss call
      upstream and store the answer. The historical behaviour. This is the only
      mode whose contract permits a future *policy-allowed semantic* reuse layer
      (#17 / RFC-004), which stays parked and forbidden in a measurement path
      (RFC-010 §2/§4), so today it is exact-match like the others.
    * ``EXACT_ONLY`` — same observable behaviour as ``RECORD_AND_REPLAY`` on
      today's exact-only cache (serve exact hits, live+store on miss), but its
      declared contract forbids *any* semantic reuse: only an exact-digest match
      is ever served. It is the named policy S3 / #17 build against.
    * ``CACHE_ONLY`` — never call upstream. A miss — or an unreachable cache — is
      a LOUD, machine-readable :class:`AnswerCacheMiss`, never a silent live call
      and never a fabricated answer. This is the CI re-run mode that guarantees
      ~0 tokens for an unchanged suite against an unchanged model, and turns a
      silent cache-off into an explicit "cache not primed".
    """

    RECORD_AND_REPLAY = "record_and_replay"
    EXACT_ONLY = "exact_only"
    CACHE_ONLY = "cache_only"

    @property
    def call_upstream_on_miss(self) -> bool:
        """Whether a miss may fall through to a live upstream ``generate()``.

        ``False`` only for :attr:`CACHE_ONLY`, which fails loud instead of
        silently going live — the RFC-010 honesty rule.
        """
        return self is not CacheMode.CACHE_ONLY

    @property
    def semantic_reuse_allowed(self) -> bool:
        """Whether the mode's contract permits a (future) semantic reuse layer.

        ``True`` only for :attr:`RECORD_AND_REPLAY`. No semantic backend exists
        today — it is parked at #17 / RFC-004 and forbidden in a measurement
        path (RFC-010 §2/§4) — so this changes no behaviour now; it pins the
        policy so ``EXACT_ONLY`` / ``CACHE_ONLY`` are guaranteed exact-digest-only
        and any future semantic layer must consult this flag before activating.
        """
        return self is CacheMode.RECORD_AND_REPLAY

    @classmethod
    def from_str(cls, value: str) -> Optional["CacheMode"]:
        """Parse a mode name (case/space-insensitive); ``None`` if unrecognized."""
        try:
            return cls(value.strip().lower())
        except ValueError:
            return None


DEFAULT_CACHE_MODE = CacheMode.RECORD_AND_REPLAY


class AnswerCacheMiss(RuntimeError):
    """Raised when a no-upstream mode cannot serve a request (RFC-010 S2, #259).

    The honesty contract: in :attr:`CacheMode.CACHE_ONLY` a missing or
    unreachable cache entry is a LOUD, machine-readable failure — never a silent
    live call and never a fabricated answer. The attributes make the failure
    assertable by callers / Robot tests.
    """

    def __init__(
        self,
        *,
        mode: "CacheMode",
        reason: str,
        key: Optional[str],
        model: Optional[str],
    ) -> None:
        self.mode = mode
        # One of: "cache-miss", "cache-unreachable", "nondeterministic-request".
        self.reason = reason
        self.key = key
        self.model = model
        super().__init__(
            f"answer cache miss in {mode.value} mode "
            f"(reason={reason}, model={model!r}, key={key!r}): refusing to call "
            "upstream. Prime the cache with a record_and_replay/verify run first."
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
    # NB: ``think`` is intentionally NOT declared here even though it is in
    # ``_KEY_ATTRS``. make_key reads it via ``getattr(client, attr, None)``, so
    # no protocol member is needed, and requiring it would exclude providers
    # (e.g. OpenAI) whose client legitimately has no ``think`` attribute (#131).
    # ``cache_context`` (RFC-010 S4, #262) is likewise NOT declared: it is an
    # optional, opt-in repo/prompt fingerprint that make_key duck-types via
    # ``getattr(client, "cache_context", None)`` and folds in only when set, so
    # every self-contained provider omits it without needing the attribute.

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

        # Model identity beyond the tag name (issue #526). An Ollama tag can be
        # repointed in place, so a client that can resolve its content digest
        # contributes it to the key. Three distinct namespaces result:
        #   * no resolver          → "model_digest" absent   (non-Ollama providers)
        #   * resolver → None      → "model_digest": null     (offline/unresolvable)
        #   * resolver → digest    → "model_digest": "sha…"   (confirmed weights)
        # A null digest never collides with a real one, so a digest-stamped
        # entry is never served when the digest cannot be re-confirmed.
        resolve_digest = getattr(client, "resolve_model_digest", None)
        if callable(resolve_digest):
            payload["model_digest"] = resolve_digest()

        # Repo / prompt context for context-sensitive suites (RFC-010 S4, #262).
        # A suite whose PROMPT embeds repo state — a pasted code snapshot, the
        # current commit, a versioned prompt template — must invalidate its own
        # cached answers when that state changes, or a code change silently
        # replays an answer about the old code. Such a suite sets
        # ``client.cache_context`` to a fingerprint of that state (e.g. the repo
        # commit plus the prompt version); it is folded into the key so a changed
        # fingerprint is a MISS, not a stale hit. It is intentionally opt-in: a
        # plain optional attribute read via getattr (shaped like ``think``, not a
        # callable resolver like ``model_digest``) and folded in with the same
        # omit-when-absent discipline — absent OR ``None`` (every provider
        # whose prompt is self-contained) omits the field entirely, so those keys
        # are byte-for-byte identical to the pre-#262 schema and no version bump
        # is needed. The dimension exists only for prompts that actually embed
        # repo state — the broader nv-cache metadata schema stays parked under #23.
        context = getattr(client, "cache_context", None)
        if context is not None:
            payload["cache_context"] = context

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

    def invalidate(
        self, *, version: Optional[str] = None, dry_run: bool = False
    ) -> int:
        """Delete cached entries by scope; return how many keys matched (RFC-010 S4, #262).

        The operator / CI affordance for busting the test cache without
        hand-editing Redis. It reuses the version namespace as the bust lever —
        the same mechanism a deliberate ``v2->v3`` schema bump uses to orphan the
        whole cache at once:

        * ``version=None`` — delete every ``rfc:answer_cache:*`` entry across all
          namespaces (the full flush).
        * ``version="vN"`` — delete only ``rfc:answer_cache:vN:*`` entries, so a
          single schema generation can be busted while others survive.

        With ``dry_run=True`` the matching keys are counted but not deleted — a
        safe preview before a destructive flush.

        Unlike :meth:`get` / :meth:`set`, this does **not** swallow a Redis
        outage into a passthrough: an operator running an explicit invalidation
        must hear that the cache was unreachable, not be told "0 keys" as if the
        cache were already clean. Connection errors propagate to the caller.
        """
        pattern = (
            f"{_KEY_PREFIX}:*" if version is None else f"{_KEY_PREFIX}:{version}:*"
        )
        # Materialize the full match set BEFORE deleting: deleting mid-SCAN
        # mutates the keyspace the cursor walks and can skip not-yet-returned
        # keys. The answer cache is bounded (deterministic requests, 7-day TTL),
        # so collecting the matches is cheap and correct.
        keys = list(self._redis.scan_iter(match=pattern, count=500))
        if not dry_run:
            for start in range(0, len(keys), 500):
                self._redis.delete(*keys[start : start + 500])
        return len(keys)

    def _note_unreachable(self, exc: BaseException) -> None:
        # Disable for the rest of the run so we never pay the timeout twice.
        self._disabled = True
        if not self._logged_unreachable:
            logger.warning(
                "Answer cache unreachable (%s); bypassing cache for this run.",
                exc,
            )
            self._logged_unreachable = True

    @property
    def version(self) -> str:
        """The active key namespace this cache reads and writes.

        Resolved from ``ANSWER_CACHE_VERSION`` by :meth:`from_env` (falling back
        to :data:`DEFAULT_VERSION`), so it is the namespace an operator is
        *actually* on — not the compiled-in default. ``rfc cache invalidate``
        with no ``--version`` busts this, so the documented default ("bust the
        current schema namespace") matches behaviour even when the env knob is
        set. A public read-only accessor so callers (the CLI, mirror-shipped)
        need not reach into the private ``_version``.
        """
        return self._version

    @property
    def available(self) -> bool:
        """False once a Redis outage has latched this cache to passthrough.

        Lets a no-upstream mode distinguish a genuine key-absent miss (``True``)
        from an unreachable cache (``False``) when reporting why it refused to
        serve — both are a loud failure under ``cache_only``, but the reason
        matters for diagnosis.
        """
        return not self._disabled


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
        mode: Optional[CacheMode] = None,
    ) -> None:
        if cache_nondeterministic is None:
            cache_nondeterministic = (
                os.getenv("ANSWER_CACHE_NONDETERMINISTIC", "") == "1"
            )
        if mode is None:
            mode = DEFAULT_CACHE_MODE
        # Bypass __setattr__ proxying for our own private attributes.
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_cache", cache)
        object.__setattr__(
            self, "_cache_nondeterministic", bool(cache_nondeterministic)
        )
        object.__setattr__(self, "_mode", mode)
        # Standard wrapper accessor (functools.wraps convention) so callers
        # that need the concrete underlying type — e.g. the OllamaClient
        # isinstance gates in keywords.py — can unwrap the proxy (#523).
        object.__setattr__(self, "__wrapped__", client)

    @property
    def cache_mode(self) -> CacheMode:
        """The active replay mode for this provider (RFC-010 S2, #259)."""
        return self._mode

    def unwrap(self) -> _CacheableClient:
        """Return the wrapped client (peels exactly one cache layer)."""
        return self._client

    def generate(self, prompt: str) -> str:
        client = self._client
        mode = self._mode

        cacheable = self._cache_nondeterministic or is_deterministic(client)
        if not cacheable:
            # A non-deterministic request is never keyed or stored, so it can
            # only be answered by a live call. A no-upstream mode must fail loud
            # rather than sneak a live call past its zero-token guarantee.
            if not mode.call_upstream_on_miss:
                raise AnswerCacheMiss(
                    mode=mode,
                    reason="nondeterministic-request",
                    key=None,
                    model=getattr(client, "model", None),
                )
            return client.generate(prompt)

        key = self._cache.make_key(client, prompt)

        cached = self._cache.get(key)
        # Symmetric read-side twin of the write guard below (#319). A blank /
        # whitespace-only stored value is never a valid answer, so serving it as
        # a confident ``cache_hit=True`` would be the residual silent pass the
        # ``cache_only`` honesty contract exists to close (RFC-010 §3). Treat it
        # as a miss: a reachable-but-blank entry flows into the miss handling
        # below — a LOUD ``cache-miss`` under ``cache_only``, a regenerate under
        # the live-on-miss modes (the blank never sticks for the TTL).
        if cached is not None and cached.strip():
            self._record_hit(client)
            return cached

        # Exact miss. Only ``record_and_replay`` / ``exact_only`` may go live;
        # ``cache_only`` refuses — a stale/missing entry is a LOUD failure, never
        # a silent live call (RFC-010 §3 honesty rule). An unreachable cache is a
        # miss too and must NOT degrade to a live call under a no-upstream mode.
        if not mode.call_upstream_on_miss:
            raise AnswerCacheMiss(
                mode=mode,
                reason="cache-miss" if self._cache.available else "cache-unreachable",
                key=key,
                model=getattr(client, "model", None),
            )

        answer = client.generate(prompt)
        # Never memoize an empty/whitespace answer: caching an error/blank
        # response would replay the failure for the whole TTL and hide a
        # transient outage or the qwen3.6 thinking-only bug (#131).
        if answer.strip():
            self._cache.set(key, answer)
        else:
            logger.debug("Skipping cache.set for empty answer (key=%s)", key)
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


__all__ = [
    "AnswerCache",
    "AnswerCacheMiss",
    "CacheMode",
    "CachingProvider",
    "DEFAULT_CACHE_MODE",
    "is_deterministic",
]
