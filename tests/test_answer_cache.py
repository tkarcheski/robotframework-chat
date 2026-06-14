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

import fakeredis
import pytest

from rfc.answer_cache import AnswerCache, CachingProvider


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
