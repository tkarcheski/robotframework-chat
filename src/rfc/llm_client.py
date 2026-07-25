"""LLM provider abstraction and factory.

Defines the ``LLMProvider`` protocol that all LLM backends must satisfy,
and a ``create_provider()`` factory for instantiation from configuration.
"""

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, Optional, runtime_checkable

from typing import Protocol

from .ollama import OllamaClient
from .routing import build_gateway_client, select_backend

if TYPE_CHECKING:
    from .answer_cache import CacheMode

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

    # The open-tolkein consumption seam (RFC-012 MS1, #324): select_backend is
    # the ONE place rfc code decides how a request routes. When
    # OPEN_TOLKEIN_BASE_URL is configured and the gateway is reachable, the
    # terminal client points at the gateway's OpenAI-compatible endpoint,
    # key-free; otherwise this is inert and the direct provider path below runs
    # unchanged. A down gateway skips-and-logs back to the direct path
    # (RFC-012 §7.2) — deciding *before* building the direct client means a
    # gateway-routed run never forces provider config (e.g. OPENAI_API_KEY) for
    # a client it will not build (#275).
    decision = select_backend(provider)
    if decision.via_gateway and decision.base_url is not None:
        client: LLMProvider = build_gateway_client(
            decision.base_url,
            contract_version=decision.contract_version,
            **kwargs,
        )
    else:
        client = _create_direct_provider(provider, kwargs)

    return _maybe_wrap_with_graylog(
        _maybe_wrap_with_console(_maybe_wrap_with_cache(client))
    )


def create_judge_provider(fallback: "LLMProvider", **kwargs: Any) -> "LLMProvider":
    """Return the pinned judge client, or *fallback* when no judge is configured.

    Grading is a measurement instrument, so it must not vary with the thing being
    measured. When ``GOLD_JUDGE_MODEL`` is set, every arm of a comparison is graded
    by that one frozen model at temperature 0 with JSON-mode responses; when it is
    unset, callers keep their historical client so non-gate suites are unaffected.

    Raises:
        SelfGradingConfigError: If the judge is the model under test.
    """
    judge_model = os.getenv("GOLD_JUDGE_MODEL", "").strip()
    if not judge_model:
        return fallback

    arm_model = os.getenv("DEFAULT_MODEL", "").strip()
    if judge_model.casefold() == arm_model.casefold():
        from .exceptions import SelfGradingConfigError

        raise SelfGradingConfigError(judge_model)

    return create_provider(
        os.getenv("GOLD_JUDGE_PROVIDER", "ollama"),
        model=judge_model,
        temperature=0.0,
        response_format="json",
        **kwargs,
    )


def _create_direct_provider(provider: str, kwargs: Dict[str, Any]) -> "LLMProvider":
    """Construct the concrete direct-path provider client (ollama/openai/vllm).

    The historical :func:`create_provider` body, unchanged in behavior. Extracted
    so the open-tolkein seam (:func:`rfc.routing.select_backend`) can decide, and
    build the gateway client, before any provider-specific config or key is
    required for the direct path.
    """
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
    return client


def _preview(text: str, limit: int = 120) -> str:
    """Collapse whitespace to single spaces and truncate for a one-line feed."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class _ConsoleFeedProvider:
    """Live per-call feed to the Robot console (``LLM_CONSOLE_FEED_ENABLED=1``).

    Emits exactly ONE self-contained line per ``generate()``:

        [<node>/<model>] <prompt preview> -> <response preview> (1.2s, 42 tok/s)

    Node = ``RFC_HOSTNAME`` (the run controller sets it to the target Ollama
    node) with the endpoint host as fallback. Parallel host-scheduler runs are
    separate ``robot`` processes sharing one terminal, so single-line prefixed
    events are the interleaving-safe format. The ollama warm-up probe
    (``generate("ping")``) is suppressed. Failures emit an ERROR line and
    re-raise — the feed observes, never swallows.
    """

    def __init__(self, inner: LLMProvider) -> None:
        self.__wrapped__ = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__wrapped__, name)

    def _node(self) -> str:
        node = os.getenv("RFC_HOSTNAME", "")
        if node:
            return node
        base_url = getattr(self.__wrapped__, "base_url", "")
        try:
            from urllib.parse import urlparse

            return urlparse(base_url).hostname or "?"
        except (ValueError, AttributeError):
            return "?"

    def _emit(self, message: str) -> None:
        try:
            from robot.api import logger as robot_logger

            robot_logger.console(message)
        except ImportError:  # outside a Robot run: plain stdout still streams
            print(message, flush=True)

    def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        import time as _time

        prefix = f"[{self._node()}/{getattr(self.__wrapped__, 'model', '?')}]"
        start = _time.monotonic()
        try:
            text = self.__wrapped__.generate(prompt, *args, **kwargs)
        except Exception as exc:
            elapsed = _time.monotonic() - start
            self._emit(
                f"{prefix} {_preview(prompt)} -> ERROR: {_preview(str(exc))} "
                f"({elapsed:.1f}s)"
            )
            raise
        if str(prompt).strip().lower() == "ping":  # ollama ensure_ready warm-up
            return text
        elapsed = _time.monotonic() - start
        metrics = getattr(self.__wrapped__, "last_metrics", None) or {}
        rate = metrics.get("eval_rate")
        rate_s = f", {rate} tok/s" if rate else ""
        self._emit(
            f"{prefix} {_preview(prompt)} -> {_preview(text)} ({elapsed:.1f}s{rate_s})"
        )
        return text


def _maybe_wrap_with_console(client: LLMProvider) -> LLMProvider:
    """Wrap *client* in the live console feed when ``LLM_CONSOLE_FEED_ENABLED=1``.

    Opt-in and dependency-free, mirroring :func:`_maybe_wrap_with_cache` /
    :func:`_maybe_wrap_with_graylog`. Placed inside the Graylog wrapper but
    outside the cache so cache hits still show up in the live feed.
    """
    if os.getenv("LLM_CONSOLE_FEED_ENABLED", "") != "1":
        return client
    return _ConsoleFeedProvider(client)


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


# RFC_RUN_MODE values that override the bare ANSWER_CACHE_ENABLED switch.
_RUN_MODE_VERIFY = "verify"
_RUN_MODE_MEASURE = "measure"
_RUN_MODE_REPLAY = "replay"
# Latches so an unrecognized value warns once per process, not per provider.
_warned_unknown_run_mode = False
_warned_unknown_cache_mode = False


def _cache_enabled_for_run_mode() -> bool:
    """Decide whether the answer cache should wrap the provider (#522).

    ``RFC_RUN_MODE`` gates the answer cache *above* the ``ANSWER_CACHE_ENABLED``
    switch so a run's intent — not just a leftover shell export — decides
    whether stored answers are replayed:

    * unset   → honor ``ANSWER_CACHE_ENABLED`` (historical behavior).
    * verify  → force the cache ON. The deterministic-only gate inside
      :mod:`rfc.answer_cache` still applies, so only reproducible requests are
      memoized; re-running an unchanged suite serves stored answers.
    * replay  → force the cache ON in ``cache_only`` mode: a miss is a LOUD
      :class:`~rfc.answer_cache.AnswerCacheMiss`, never a silent live call — the
      CI zero-token re-run guarantee (RFC-010 S2, #259). See
      :func:`_cache_mode_for_run`.
    * measure → force the cache OFF even if ``ANSWER_CACHE_ENABLED=1``, so a
      grading/measurement run can never replay a stale answer just because the
      switch was left on in the shell.
    * unknown → warn once and fall back to the unset behavior.
    """
    mode = os.getenv("RFC_RUN_MODE", "").strip().lower()
    enabled = os.getenv("ANSWER_CACHE_ENABLED", "") == "1"

    if mode == _RUN_MODE_MEASURE:
        return False
    if mode in (_RUN_MODE_VERIFY, _RUN_MODE_REPLAY):
        return True
    if mode:  # non-empty but not a recognized mode
        global _warned_unknown_run_mode
        if not _warned_unknown_run_mode:
            logger.warning(
                "RFC_RUN_MODE=%r is not recognized (expected 'verify', 'replay', "
                "or 'measure'); ignoring it and honoring ANSWER_CACHE_ENABLED.",
                mode,
            )
            _warned_unknown_run_mode = True
    return enabled


def _cache_mode_for_run() -> "CacheMode":
    """Select the answer-cache replay mode for this run (RFC-010 S2, #259).

    Only consulted when the cache is enabled (:func:`_cache_enabled_for_run_mode`
    returned ``True``). Precedence, highest first:

    1. ``RFC_RUN_MODE=replay`` pins :attr:`~rfc.answer_cache.CacheMode.CACHE_ONLY`
       and cannot be downgraded by ``ANSWER_CACHE_MODE`` — the CI zero-token
       guarantee must not be silently weakened by a leftover shell export
       (symmetric with ``measure`` unconditionally forcing the cache off).
    2. Otherwise an explicit ``ANSWER_CACHE_MODE`` (``record_and_replay`` /
       ``exact_only`` / ``cache_only``) selects the mode; an unrecognized value
       warns once and falls back to the default.
    3. Otherwise the default :attr:`~rfc.answer_cache.CacheMode.RECORD_AND_REPLAY`
       (historical behavior — covers ``verify`` and a bare ``ANSWER_CACHE_ENABLED=1``).
    """
    from .answer_cache import DEFAULT_CACHE_MODE, CacheMode

    if os.getenv("RFC_RUN_MODE", "").strip().lower() == _RUN_MODE_REPLAY:
        return CacheMode.CACHE_ONLY

    raw = os.getenv("ANSWER_CACHE_MODE", "").strip()
    if raw:
        mode = CacheMode.from_str(raw)
        if mode is not None:
            return mode
        global _warned_unknown_cache_mode
        if not _warned_unknown_cache_mode:
            logger.warning(
                "ANSWER_CACHE_MODE=%r is not recognized (expected "
                "'record_and_replay', 'exact_only', or 'cache_only'); using %s.",
                raw,
                DEFAULT_CACHE_MODE.value,
            )
            _warned_unknown_cache_mode = True
    return DEFAULT_CACHE_MODE


def _maybe_wrap_with_cache(client: LLMProvider) -> LLMProvider:
    """Wrap *client* in a caching layer for cache-enabled runs (#522).

    Opt-in by design: measurement runs leave the cache off so every answer is
    a fresh measurement. When enabled, the wrapper memoizes deterministic
    ``generate()`` calls in Redis and degrades to a passthrough if Redis is
    unreachable — a down cache must never fail a test.

    Whether the cache is enabled is decided by
    :func:`_cache_enabled_for_run_mode`, which lets ``RFC_RUN_MODE``
    (verify/replay/measure) override the bare ``ANSWER_CACHE_ENABLED`` switch;
    when enabled, :func:`_cache_mode_for_run` selects the replay mode (RFC-010
    S2, #259).
    """
    if not _cache_enabled_for_run_mode():
        return client

    from .answer_cache import AnswerCache, CachingProvider

    cache = AnswerCache.from_env()
    return CachingProvider(client, cache, mode=_cache_mode_for_run())


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
