"""Tests for the Redis-backed answer cache (issue #522).

These tests use ``fakeredis`` exclusively — no live Redis and no live LLM
calls. They cover:

* cache-key stability and per-parameter sensitivity (every output-affecting
  attribute changes the key);
* get / set round-trips and TTL application;
* the deterministic-only gate (``temperature>0`` with no seed is not cached
  unless explicitly overridden);
* the provenance flag (``cache_hit=true`` recorded in ``last_metrics`` on a
  hit);
* graceful passthrough when Redis is unreachable (the cache never fails a
  request).
"""

from typing import Any, Dict, List, Optional

import pytest

# ``fakeredis`` lives in the ``dev`` optional-dependency extra (pyproject.toml),
# not the base install. Importing it at module scope would raise during
# collection on a non-dev env and abort the *entire* suite, so skip this module
# cleanly instead (see CLAUDE.md § Rules: prefer skip-and-log for optional deps).
fakeredis = pytest.importorskip("fakeredis")

from rfc.answer_cache import (  # noqa: E402
    DEFAULT_CACHE_MODE,
    AnswerCache,
    AnswerCacheMiss,
    CacheMode,
    CachingProvider,
)


# ── Test doubles ────────────────────────────────────────────────────────


class FakeProvider:
    """Minimal stand-in for an LLM client exposing the cache key attrs.

    Records every prompt passed to :meth:`generate` so tests can assert
    whether the wrapped provider was actually called (cache miss) or
    bypassed (cache hit).
    """

    def __init__(self, **attrs: Any) -> None:
        self.model = attrs.get("model", "test-model")
        self.base_url = attrs.get("base_url", "http://localhost:11434")
        self.temperature = attrs.get("temperature", 0.0)
        self.max_tokens = attrs.get("max_tokens", 256)
        self.seed = attrs.get("seed", None)
        self.top_p = attrs.get("top_p", None)
        self.top_k = attrs.get("top_k", None)
        self.num_ctx = attrs.get("num_ctx", None)
        self.response_format = attrs.get("response_format", None)
        self.keep_alive = attrs.get("keep_alive", None)
        self.think = attrs.get("think", None)
        self.last_metrics: Optional[Dict[str, Any]] = None
        self._answer = attrs.get("answer", "the answer")
        self.calls: List[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        self.last_metrics = {"model_name": self.model, "eval_count": 7}
        return self._answer

    # An extra method to prove transparent attribute proxying works.
    def some_other_method(self) -> str:
        return "proxied"


class UnreachableRedis:
    """A redis-py-compatible client whose every op raises ConnectionError."""

    def get(self, *_a: Any, **_k: Any) -> Any:
        import redis

        raise redis.ConnectionError("redis down")

    def set(self, *_a: Any, **_k: Any) -> Any:
        import redis

        raise redis.ConnectionError("redis down")


def make_cache(**kwargs: Any) -> AnswerCache:
    return AnswerCache(redis_client=fakeredis.FakeStrictRedis(), **kwargs)


# Sentinel: build a provider that exposes NO resolver at all (models a
# non-Ollama provider), keeping the class — and thus provider_type — constant
# across comparisons so only the digest field differs.
_NO_RESOLVER = object()


class MaybeDigestProvider(FakeProvider):
    """FakeProvider that optionally exposes ``resolve_model_digest`` (#526).

    ``digest=_NO_RESOLVER`` sets the attribute to a non-callable so
    ``make_key`` omits ``model_digest`` entirely (as a provider lacking the
    method would); any other value (including ``None``) exposes a resolver
    returning it. Using one class keeps ``provider_type`` constant so tests
    isolate the digest's effect on the key.
    """

    def __init__(self, digest: Any = _NO_RESOLVER, **attrs: Any) -> None:
        super().__init__(**attrs)
        if digest is _NO_RESOLVER:
            self.resolve_model_digest = None  # non-callable → field omitted
        else:
            self._digest_value = digest
            self.resolve_model_digest = lambda: self._digest_value


# ── Cache key: stability ────────────────────────────────────────────────


def test_key_is_stable_for_identical_requests():
    cache = make_cache()
    p1 = FakeProvider()
    p2 = FakeProvider()
    assert cache.make_key(p1, "hello") == cache.make_key(p2, "hello")


def test_key_is_deterministic_across_calls():
    cache = make_cache()
    p = FakeProvider()
    assert cache.make_key(p, "hello") == cache.make_key(p, "hello")


def test_key_is_sha256_hex():
    cache = make_cache()
    key = cache.make_key(FakeProvider(), "hello")
    # key embeds a namespace prefix; the digest portion is 64 hex chars.
    digest = key.rsplit(":", 1)[-1]
    assert len(digest) == 64
    int(digest, 16)  # raises if not hex


# ── Cache key: per-parameter sensitivity ────────────────────────────────


@pytest.mark.parametrize(
    "attr,value",
    [
        ("model", "other-model"),
        ("base_url", "http://other:11434"),
        ("temperature", 0.7),
        ("max_tokens", 512),
        ("seed", 42),
        ("top_p", 0.9),
        ("top_k", 40),
        ("num_ctx", 8192),
        ("response_format", "json"),
        ("think", True),
    ],
)
def test_each_output_affecting_param_changes_the_key(attr, value):
    cache = make_cache()
    base = FakeProvider()
    changed = FakeProvider(**{attr: value})
    assert cache.make_key(base, "hello") != cache.make_key(changed, "hello"), (
        f"changing {attr} did not change the cache key — would serve wrong answers"
    )


def test_prompt_changes_the_key():
    cache = make_cache()
    p = FakeProvider()
    assert cache.make_key(p, "hello") != cache.make_key(p, "goodbye")


def test_version_namespace_changes_the_key():
    p = FakeProvider()
    k_v1 = make_cache(version="v1").make_key(p, "hello")
    k_v2 = make_cache(version="v2").make_key(p, "hello")
    assert k_v1 != k_v2


def test_provider_type_changes_the_key():
    """Two clients with identical attrs but different classes must not collide."""

    class OtherProvider(FakeProvider):
        pass

    cache = make_cache()
    assert cache.make_key(FakeProvider(), "hello") != cache.make_key(
        OtherProvider(), "hello"
    )


# ── Cache key: model digest (issue #526) ────────────────────────────────


def test_default_namespace_is_v2():
    """The shipped default namespace is v2 — the digest-in-key schema. A v1
    (tag-only) cache is deliberately invalidated by the bump."""
    cache = make_cache()
    key = cache.make_key(FakeProvider(), "hello")
    assert key.startswith("rfc:answer_cache:v2:")


def test_provider_without_resolver_builds_key_and_omits_digest():
    """A plain client with no resolver still keys fine (non-Ollama providers)."""
    cache = make_cache()
    key = cache.make_key(FakeProvider(), "hello")  # must not raise
    assert key.startswith("rfc:answer_cache:v2:")


def test_changed_digest_changes_the_key():
    """A tag repointed to new weights (new digest) must not reuse the old key."""
    cache = make_cache()
    old = MaybeDigestProvider(digest="sha256:AAA")
    new = MaybeDigestProvider(digest="sha256:BBB")
    assert cache.make_key(old, "hello") != cache.make_key(new, "hello"), (
        "same tag, new weights collided on one key — would serve stale answers"
    )


def test_same_digest_is_stable():
    cache = make_cache()
    a = MaybeDigestProvider(digest="sha256:AAA")
    b = MaybeDigestProvider(digest="sha256:AAA")
    assert cache.make_key(a, "hello") == cache.make_key(b, "hello")


def test_omitted_null_and_real_digests_are_three_namespaces():
    """No resolver, a null digest, and a real digest are all distinct keys, so
    a digest-stamped entry is never served when the digest can't be reconfirmed
    (offline → null), and never crosses into the no-resolver namespace."""
    cache = make_cache()
    k_absent = cache.make_key(MaybeDigestProvider(_NO_RESOLVER), "hello")
    k_null = cache.make_key(MaybeDigestProvider(digest=None), "hello")
    k_real = cache.make_key(MaybeDigestProvider(digest="sha256:AAA"), "hello")
    assert k_absent != k_null  # omitted field ≠ explicit null
    assert k_null != k_real  # unconfirmed (null) ≠ confirmed digest
    assert k_absent != k_real


def test_make_key_calls_resolver_once():
    """make_key duck-types and invokes the resolver exactly once per key."""
    cache = make_cache()
    calls = {"n": 0}

    class CountingProvider(FakeProvider):
        def resolve_model_digest(self) -> Optional[str]:
            calls["n"] += 1
            return "sha256:XYZ"

    cache.make_key(CountingProvider(), "hello")
    assert calls["n"] == 1


# ── get / set / TTL ─────────────────────────────────────────────────────


def test_set_then_get_round_trip():
    cache = make_cache()
    cache.set("k1", "stored answer")
    assert cache.get("k1") == "stored answer"


def test_get_missing_key_returns_none():
    cache = make_cache()
    assert cache.get("nope") is None


def test_set_applies_ttl():
    fake = fakeredis.FakeStrictRedis()
    cache = AnswerCache(redis_client=fake, ttl_seconds=1234)
    cache.set("k1", "answer")
    ttl = fake.ttl("k1")
    assert 0 < ttl <= 1234


# ── CachingProvider: hit / miss behaviour ───────────────────────────────


def test_miss_calls_underlying_and_stores():
    cache = make_cache()
    inner = FakeProvider(answer="fresh")
    wrapped = CachingProvider(inner, cache)

    result = wrapped.generate("question")

    assert result == "fresh"
    assert inner.calls == ["question"]  # underlying was hit once
    # second identical call should be served from cache, not the provider
    result2 = wrapped.generate("question")
    assert result2 == "fresh"
    assert inner.calls == ["question"]  # NOT called again


def test_hit_sets_provenance_flag():
    cache = make_cache()
    inner = FakeProvider(answer="cached value")
    wrapped = CachingProvider(inner, cache)

    wrapped.generate("q")  # prime the cache (miss)
    inner.last_metrics = None  # reset to prove the hit repopulates it

    wrapped.generate("q")  # hit

    assert wrapped.last_metrics is not None
    assert wrapped.last_metrics.get("cache_hit") is True


def test_miss_does_not_set_cache_hit_true():
    cache = make_cache()
    inner = FakeProvider(answer="x")
    wrapped = CachingProvider(inner, cache)

    wrapped.generate("q")  # miss

    # On a miss the underlying metrics flow through; cache_hit must be falsey.
    assert not (wrapped.last_metrics or {}).get("cache_hit")


# ── Never memoize an empty/error answer (issue #131) ────────────────────


def test_empty_answer_is_not_cached():
    cache = make_cache()
    inner = FakeProvider(answer="")
    wrapped = CachingProvider(inner, cache)

    assert wrapped.generate("q") == ""
    # A second identical call must re-hit the provider — the blank was NOT
    # memoized, so a transient outage / thinking-only bug doesn't stick for 7d.
    assert wrapped.generate("q") == ""
    assert inner.calls == ["q", "q"]


def test_whitespace_answer_is_not_cached():
    cache = make_cache()
    inner = FakeProvider(answer="   \n  ")
    wrapped = CachingProvider(inner, cache)

    wrapped.generate("q")
    wrapped.generate("q")
    assert inner.calls == ["q", "q"]


def test_nonempty_answer_is_cached_after_empty():
    """Once the provider returns real content, it is memoized normally."""
    cache = make_cache()
    inner = FakeProvider(answer="")
    wrapped = CachingProvider(inner, cache)

    wrapped.generate("q")  # empty — not cached
    inner._answer = "now answered"
    assert wrapped.generate("q") == "now answered"  # miss, provider hit again
    assert wrapped.generate("q") == "now answered"  # served from cache now
    assert inner.calls == ["q", "q"]  # third call was a cache hit


# ── Deterministic gate ──────────────────────────────────────────────────


def test_nondeterministic_request_is_not_cached_by_default():
    cache = make_cache()
    inner = FakeProvider(temperature=0.7, seed=None, answer="varies")
    wrapped = CachingProvider(inner, cache)

    wrapped.generate("q")
    wrapped.generate("q")

    # Both calls must reach the provider — nondeterministic output isn't cached.
    assert inner.calls == ["q", "q"]


def test_temperature_zero_is_cached():
    cache = make_cache()
    inner = FakeProvider(temperature=0.0, answer="det")
    wrapped = CachingProvider(inner, cache)
    wrapped.generate("q")
    wrapped.generate("q")
    assert inner.calls == ["q"]  # cached after first


def test_seeded_nonzero_temperature_is_cached():
    cache = make_cache()
    inner = FakeProvider(temperature=0.7, seed=123, answer="seeded")
    wrapped = CachingProvider(inner, cache)
    wrapped.generate("q")
    wrapped.generate("q")
    assert inner.calls == ["q"]  # seed makes it reproducible → cacheable


def test_nondeterministic_override_enables_caching():
    cache = make_cache()
    inner = FakeProvider(temperature=0.7, seed=None, answer="forced")
    wrapped = CachingProvider(inner, cache, cache_nondeterministic=True)
    wrapped.generate("q")
    wrapped.generate("q")
    assert inner.calls == ["q"]  # override forces caching


# ── Redis-down passthrough ──────────────────────────────────────────────


def test_get_on_redis_down_returns_none():
    cache = AnswerCache(redis_client=UnreachableRedis())
    assert cache.get("anything") is None  # logged + bypassed, not raised


def test_set_on_redis_down_does_not_raise():
    cache = AnswerCache(redis_client=UnreachableRedis())
    cache.set("k", "v")  # must not raise


def test_caching_provider_passthrough_when_redis_down():
    cache = AnswerCache(redis_client=UnreachableRedis())
    inner = FakeProvider(answer="live")
    wrapped = CachingProvider(inner, cache)

    # Every call reaches the provider; cache never blocks or fails the request.
    assert wrapped.generate("q") == "live"
    assert wrapped.generate("q") == "live"
    assert inner.calls == ["q", "q"]


# ── Transparent attribute proxying ──────────────────────────────────────


def test_caching_provider_proxies_attributes():
    cache = make_cache()
    inner = FakeProvider(model="m", num_ctx=4096)
    wrapped = CachingProvider(inner, cache)

    assert wrapped.model == "m"
    assert wrapped.num_ctx == 4096
    assert wrapped.some_other_method() == "proxied"


def test_caching_provider_proxies_attribute_writes():
    cache = make_cache()
    inner = FakeProvider()
    wrapped = CachingProvider(inner, cache)

    wrapped.model = "switched"
    assert inner.model == "switched"  # write proxied to the real client


def test_caching_provider_exposes_full_llm_provider_surface():
    """The wrapper must expose every attribute/method create_provider's
    callers rely on, so it is a drop-in for the real provider.

    (We assert the structural surface rather than ``isinstance`` against the
    runtime-checkable Protocol: CPython's protocol instance-check does not see
    attributes resolved purely through ``__getattr__`` on a proxy, even though
    they are reachable — a limitation of the check, not of the wrapper.)
    """
    from rfc.llm_client import LLMProvider

    cache = make_cache()
    wrapped = CachingProvider(FakeProvider(), cache)
    for attr in LLMProvider.__protocol_attrs__:
        assert hasattr(wrapped, attr), f"wrapper missing provider attr {attr!r}"
    assert callable(wrapped.generate)


def test_caching_provider_isinstance_transparent():
    """CachingProvider.__class__ delegates to the wrapped type, making
    isinstance() transparent to callers (#531).

    When ``ANSWER_CACHE_ENABLED=1``, ``create_provider()`` returns a
    ``CachingProvider`` wrapper. Direct ``isinstance(p, OllamaClient)`` checks
    in test assertions (and any production code that hasn't migrated to
    ``as_ollama()``) were silently broken. Fixing ``__class__`` to delegate to
    the inner type makes the wrapper invisible to isinstance without altering
    the real ``type()`` or the ``as_ollama()`` unwrap path.
    """
    from rfc.ollama import OllamaClient

    cache = make_cache()
    inner = OllamaClient(base_url="http://localhost:11434", model="m")
    wrapped = CachingProvider(inner, cache)

    # isinstance() sees through the wrapper after the __class__ fix.
    assert isinstance(wrapped, OllamaClient)
    # type() still returns CachingProvider — __class__ is a virtual class only.
    assert type(wrapped) is CachingProvider
    # as_ollama() continues to work and returns the concrete inner client.
    from rfc.llm_client import as_ollama

    assert as_ollama(wrapped) is inner


# ── Finding 1: cache-hit metrics are honest, not inherited (#523) ────────


def test_hit_metrics_are_zero_cost_not_inherited():
    """A cache hit did zero model work, so its metrics must report zero —
    never the token counts/durations of the prior fresh generation."""
    cache = make_cache()
    inner = FakeProvider(model="m", answer="cached")
    wrapped = CachingProvider(inner, cache)

    wrapped.generate("q")  # miss → inner.last_metrics = {model_name:m, eval_count:7}
    wrapped.generate("q")  # hit

    m = wrapped.last_metrics
    assert m is not None
    assert m["cache_hit"] is True
    assert m["model_name"] == "m"
    assert m["eval_count"] == 0  # NOT 7 from the prior fresh call
    assert m["prompt_eval_count"] == 0
    assert m["total_duration_ns"] == 0
    assert m["eval_rate"] is None  # rate undefined, not fabricated


def test_hit_metrics_schema_matches_miss_schema():
    """A hit row carries the same keys as a miss row so result columns stay
    populated."""
    from rfc.ollama import _extract_metrics

    miss_keys = set(_extract_metrics({}, "m")) | {"cache_hit"}
    cache = make_cache()
    wrapped = CachingProvider(FakeProvider(model="m"), cache)
    wrapped.generate("q")
    wrapped.generate("q")  # hit
    assert set(wrapped.last_metrics) == miss_keys


# ── Finding 2: Redis timeouts + outage latch (#523) ─────────────────────


class CountingUnreachableRedis:
    """Records how many times each op was attempted before failing."""

    def __init__(self) -> None:
        self.get_calls = 0
        self.set_calls = 0

    def get(self, *_a: Any, **_k: Any) -> Any:
        import redis

        self.get_calls += 1
        raise redis.ConnectionError("redis down")

    def set(self, *_a: Any, **_k: Any) -> Any:
        import redis

        self.set_calls += 1
        raise redis.ConnectionError("redis down")


def test_from_env_passes_finite_socket_timeouts(monkeypatch):
    import redis

    captured: Dict[str, Any] = {}

    def fake_from_url(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        return fakeredis.FakeStrictRedis()

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(fake_from_url))
    AnswerCache.from_env()
    assert captured.get("socket_connect_timeout", 0) > 0
    assert captured.get("socket_timeout", 0) > 0


def test_redis_outage_latches_and_stops_reattempting():
    redis_dbl = CountingUnreachableRedis()
    cache = AnswerCache(redis_client=redis_dbl)

    assert cache.get("k1") is None  # first attempt hits redis, fails, latches
    assert cache.get("k2") is None  # short-circuited
    cache.set("k3", "v")  # short-circuited

    assert redis_dbl.get_calls == 1  # only the first lookup actually tried
    assert redis_dbl.set_calls == 0  # cache disabled before set was attempted


# ── Finding 3: unwrap-at-the-seam for isinstance gates (#523) ────────────


def test_unwrap_provider_returns_inner_client():
    from rfc.llm_client import unwrap_provider

    inner = FakeProvider()
    wrapped = CachingProvider(inner, make_cache())
    assert unwrap_provider(wrapped) is inner
    # a non-wrapped client unwraps to itself
    assert unwrap_provider(inner) is inner


def test_as_ollama_sees_through_wrapper():
    from rfc.llm_client import as_ollama
    from rfc.ollama import OllamaClient

    inner = OllamaClient(base_url="http://localhost:11434", model="m")
    wrapped = CachingProvider(inner, make_cache())
    assert as_ollama(wrapped) is inner
    assert as_ollama(inner) is inner


def test_as_ollama_none_for_non_ollama_client():
    from rfc.llm_client import as_ollama

    wrapped = CachingProvider(FakeProvider(), make_cache())
    assert as_ollama(wrapped) is None


# ── RFC-010 S2: replay modes (#259, scopes #19) ─────────────────────────
#
# The load-bearing honesty rule: a stale/missing entry must fail explicitly —
# never silently pass and never silently go live. cache_only enforces it; the
# two live-on-miss modes keep the historical behaviour.


def test_default_mode_is_record_and_replay():
    """A CachingProvider built without a mode is record_and_replay (unchanged)."""
    assert DEFAULT_CACHE_MODE is CacheMode.RECORD_AND_REPLAY
    wrapped = CachingProvider(FakeProvider(), make_cache())
    assert wrapped.cache_mode is CacheMode.RECORD_AND_REPLAY


def test_mode_contract_flags():
    """Each mode's policy flags encode its contract (the pinned distinction)."""
    # Only cache_only refuses to go live on a miss.
    assert CacheMode.RECORD_AND_REPLAY.call_upstream_on_miss is True
    assert CacheMode.EXACT_ONLY.call_upstream_on_miss is True
    assert CacheMode.CACHE_ONLY.call_upstream_on_miss is False
    # Only record_and_replay's contract permits a future semantic reuse layer;
    # exact_only / cache_only are guaranteed exact-digest-only.
    assert CacheMode.RECORD_AND_REPLAY.semantic_reuse_allowed is True
    assert CacheMode.EXACT_ONLY.semantic_reuse_allowed is False
    assert CacheMode.CACHE_ONLY.semantic_reuse_allowed is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("record_and_replay", CacheMode.RECORD_AND_REPLAY),
        ("exact_only", CacheMode.EXACT_ONLY),
        ("cache_only", CacheMode.CACHE_ONLY),
        ("  CACHE_ONLY  ", CacheMode.CACHE_ONLY),  # case/space-insensitive
        ("bogus", None),
        ("", None),
    ],
)
def test_cache_mode_from_str(raw, expected):
    assert CacheMode.from_str(raw) is expected


# record_and_replay (default) — serve on hit, live+store on miss.


def test_record_and_replay_miss_goes_live_and_stores():
    cache = make_cache()
    inner = FakeProvider(answer="fresh")
    wrapped = CachingProvider(inner, cache, mode=CacheMode.RECORD_AND_REPLAY)

    assert wrapped.generate("q") == "fresh"  # miss → live
    assert wrapped.generate("q") == "fresh"  # hit → served, provider not re-hit
    assert inner.calls == ["q"]


# exact_only — same observable behaviour as record_and_replay today, but the
# contract forbids any semantic reuse.


def test_exact_only_miss_goes_live_and_stores():
    cache = make_cache()
    inner = FakeProvider(answer="fresh")
    wrapped = CachingProvider(inner, cache, mode=CacheMode.EXACT_ONLY)

    assert wrapped.generate("q") == "fresh"  # miss → live
    assert wrapped.generate("q") == "fresh"  # exact hit → served
    assert inner.calls == ["q"]


def test_exact_only_nondeterministic_still_bypasses_to_live():
    """A non-deterministic request in a live-on-miss mode goes live (not stored)."""
    cache = make_cache()
    inner = FakeProvider(temperature=0.7, seed=None, answer="varies")
    wrapped = CachingProvider(inner, cache, mode=CacheMode.EXACT_ONLY)

    wrapped.generate("q")
    wrapped.generate("q")
    assert inner.calls == ["q", "q"]  # both reached the provider


# cache_only — never call upstream; a miss/outage/nondeterministic request is a
# LOUD, machine-readable failure.


def test_cache_only_hit_serves_without_upstream():
    """cache_only serves a primed exact hit with zero upstream calls."""
    redis = fakeredis.FakeStrictRedis()
    # Prime via a record_and_replay run sharing the same Redis.
    primer = FakeProvider(answer="primed")
    CachingProvider(primer, AnswerCache(redis_client=redis)).generate("q")

    inner = FakeProvider(answer="SHOULD_NOT_RUN")
    wrapped = CachingProvider(
        inner, AnswerCache(redis_client=redis), mode=CacheMode.CACHE_ONLY
    )
    assert wrapped.generate("q") == "primed"
    assert inner.calls == []  # upstream never called
    assert wrapped.last_metrics is not None
    assert wrapped.last_metrics.get("cache_hit") is True


def test_cache_only_miss_raises_and_never_goes_live():
    """A genuine miss is a loud AnswerCacheMiss — never a silent live call."""
    cache = make_cache()
    inner = FakeProvider(answer="never")
    wrapped = CachingProvider(inner, cache, mode=CacheMode.CACHE_ONLY)

    with pytest.raises(AnswerCacheMiss) as excinfo:
        wrapped.generate("unprimed")

    err = excinfo.value
    assert inner.calls == []  # the honesty rule: zero upstream calls
    # Machine-readable fields so a caller / Robot test can assert on the failure.
    assert err.mode is CacheMode.CACHE_ONLY
    assert err.reason == "cache-miss"
    assert err.key is not None
    assert err.model == inner.model


def test_cache_only_outage_is_loud_not_silent_passthrough():
    """A down cache under cache_only fails loud — it must NOT go live.

    This is the deliberate exception to the passthrough rule: silently going
    live would break cache_only's zero-token guarantee.
    """
    inner = FakeProvider(answer="never")
    wrapped = CachingProvider(
        inner, AnswerCache(redis_client=UnreachableRedis()), mode=CacheMode.CACHE_ONLY
    )

    with pytest.raises(AnswerCacheMiss) as excinfo:
        wrapped.generate("q")

    assert inner.calls == []
    assert excinfo.value.reason == "cache-unreachable"


def test_cache_only_nondeterministic_request_is_loud():
    """A non-cacheable request under cache_only fails loud, not live."""
    cache = make_cache()
    inner = FakeProvider(temperature=0.7, seed=None, answer="never")
    wrapped = CachingProvider(inner, cache, mode=CacheMode.CACHE_ONLY)

    with pytest.raises(AnswerCacheMiss) as excinfo:
        wrapped.generate("q")

    assert inner.calls == []
    assert excinfo.value.reason == "nondeterministic-request"
    assert excinfo.value.key is None  # never keyed


def test_answer_cache_available_reflects_outage_latch():
    up = make_cache()
    assert up.available is True

    down = AnswerCache(redis_client=UnreachableRedis())
    assert down.available is True  # not tripped until first use
    down.get("k")  # latches _disabled
    assert down.available is False


# ── test-design adversarial coverage for PR #317 (RFC-010 S2 verdict) ────
#
# Added by test-design (Mr. Meeseeks) attacking the honesty contract on angles
# the engineering suite did not already pin: a MID-run Redis drop (vs. an outage
# present from the start), digest-keying stability across the record→replay
# seam, a model re-pull changing the digest, and the read-side blank-value gap
# (characterized here, tracked as from:testing #319).


class _FlakyRedis:
    """fakeredis that starts healthy then drops mid-run once ``down`` is set.

    Models a Redis connection dying *after* the provider has already served a
    healthy hit — distinct from ``UnreachableRedis``, which is down from op #1.
    """

    def __init__(self) -> None:
        self._backing = fakeredis.FakeStrictRedis()
        self.down = False

    def get(self, *a: Any, **k: Any) -> Any:
        if self.down:
            import redis

            raise redis.ConnectionError("redis dropped mid-run")
        return self._backing.get(*a, **k)

    def set(self, *a: Any, **k: Any) -> Any:
        if self.down:
            import redis

            raise redis.ConnectionError("redis dropped mid-run")
        return self._backing.set(*a, **k)


def test_cache_only_redis_drops_midrun_is_loud_not_live():
    """A Redis outage that begins mid-run still fails LOUD — never a live call.

    Serves one healthy hit, then Redis dies; the next key must be a loud
    ``cache-unreachable`` miss with zero upstream calls, not a silent
    degrade-to-live that would breach the zero-token guarantee.
    """
    flaky = _FlakyRedis()
    # Prime one key while healthy (record_and_replay over the same store).
    CachingProvider(
        FakeProvider(answer="primed"), AnswerCache(redis_client=flaky)
    ).generate("primed-q")

    inner = FakeProvider(answer="SHOULD_NOT_RUN")
    wrapped = CachingProvider(
        inner, AnswerCache(redis_client=flaky), mode=CacheMode.CACHE_ONLY
    )
    assert wrapped.generate("primed-q") == "primed"  # healthy hit
    assert inner.calls == []

    flaky.down = True  # connection drops mid-run
    with pytest.raises(AnswerCacheMiss) as excinfo:
        wrapped.generate("other-q")
    assert inner.calls == []  # STILL zero upstream after the drop
    assert excinfo.value.reason == "cache-unreachable"


def test_cache_key_is_mode_independent_across_record_replay_seam():
    """A digest-keyed entry primed under record_and_replay is served under
    cache_only: the key is computed by AnswerCache (mode-independent), so the
    record→replay seam is a hit. A mode-dependent key would silently zero the
    hit rate. Exercises the #526 ``model_digest`` field on both sides.
    """
    redis = fakeredis.FakeStrictRedis()
    CachingProvider(
        MaybeDigestProvider(digest="sha-A", answer="primed"),
        AnswerCache(redis_client=redis),
    ).generate("q")  # record_and_replay (default)

    inner = MaybeDigestProvider(digest="sha-A", answer="SHOULD_NOT_RUN")
    wrapped = CachingProvider(
        inner, AnswerCache(redis_client=redis), mode=CacheMode.CACHE_ONLY
    )
    assert wrapped.generate("q") == "primed"  # cross-mode hit on the same key
    assert inner.calls == []


def test_cache_only_model_repull_new_digest_is_loud_miss():
    """A model re-pull changes the resolved digest (#526), changing the key:
    cache_only must MISS LOUD on the new digest, never serve the stale-weights
    answer that was keyed under the old digest.
    """
    redis = fakeredis.FakeStrictRedis()
    CachingProvider(
        MaybeDigestProvider(digest="sha-old", answer="old-weights"),
        AnswerCache(redis_client=redis),
    ).generate("q")  # recorded under the old digest

    new = MaybeDigestProvider(digest="sha-new", answer="SHOULD_NOT_RUN")
    wrapped = CachingProvider(
        new, AnswerCache(redis_client=redis), mode=CacheMode.CACHE_ONLY
    )
    with pytest.raises(AnswerCacheMiss) as excinfo:
        wrapped.generate("q")
    assert new.calls == []  # zero upstream — no stale-weights hit
    assert excinfo.value.reason == "cache-miss"  # key-absent, not an outage


@pytest.mark.parametrize("blank", ["", "   "])
def test_cache_only_serves_blank_stored_value_as_hit_characterization(blank):
    """CHARACTERIZATION of a known read-side gap (from:testing #319).

    The write side never memoizes a blank answer, but the read side serves any
    ``cached is not None`` value — so a blank entry written out-of-band / by
    legacy data is replayed as a confident cache_hit under cache_only rather
    than a loud miss. The zero-token guarantee is intact (no upstream call);
    this pins the CURRENT behaviour so a future read-side blank guard (#319) is
    a deliberate, tested change.
    """
    redis = fakeredis.FakeStrictRedis()
    key = AnswerCache(redis_client=redis).make_key(FakeProvider(), "q")
    redis.set(key, blank)  # out-of-band blank; current code never writes this

    inner = FakeProvider(answer="SHOULD_NOT_RUN")
    wrapped = CachingProvider(
        inner, AnswerCache(redis_client=redis), mode=CacheMode.CACHE_ONLY
    )
    assert wrapped.generate("q") == blank  # served blank as a "hit"
    assert inner.calls == []  # zero upstream — the guarantee still holds
    assert wrapped.last_metrics is not None
    assert wrapped.last_metrics.get("cache_hit") is True
