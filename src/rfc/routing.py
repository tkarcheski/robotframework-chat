"""The open-tolkein consumption seam (RFC-012 MS1, #324).

``select_backend`` is the ONE place ``rfc`` code decides *how* a request routes.
Today it resolves to the existing providers (the :func:`rfc.llm_client.create_provider`
path, unchanged) — this is the **seam, not the cutover**. When
``OPEN_TOLKEIN_BASE_URL`` is configured, the terminal client instead points at
the standalone open-tolkein gateway's OpenAI-compatible endpoint
(``tkarcheski/open-tolkein``, RFC-012), which owns the cache → fleet → BYOK
routing behind one door.

Three invariants this seam holds (RFC-012 §7.2):

* **Key-free by construction (the #275 lesson).** The gateway holds every BYOK
  key; this side reads *no* ``*_API_KEY`` env var and carries no provider
  catalog. The gateway client is built with a constant, non-secret placeholder
  token (:data:`GATEWAY_PLACEHOLDER_TOKEN`) — the same shape the ``vllm`` path
  already uses. The public mirror inherits a seam that is inert and key-free.
* **Skip-and-log if unreachable.** A down gateway must never fail a cached or
  local test run: :func:`select_backend` probes the gateway and, when it cannot
  be reached, logs a route note and falls back to the direct provider path so
  the local answer-cache replay tape can still serve the run.
* **Honest route provenance.** :class:`_GatewayProvenanceProvider` threads the
  route note (served-via, gateway ``base_url``, pinned contract version) into
  the existing ``last_metrics`` metadata path the spine already records. Per-hop
  cost/latency/compute and the RFC-008 ``served_by`` column are MS5 (#328); the
  column-shape question (RFC-012 §9.Q3) stays deferred to #320/#328. This seam
  never fabricates cost or host numbers.

``RoutePolicy`` (the three §3.3 knobs — ``locality`` · ``cache_mode`` ·
``cost_ceiling``) is defined here and seeded from the environment; MS1 records it
on the decision. Transmitting it over the wire and enforcing locality
(``local_only`` must not egress) is MS3/MS4 (#326/#327).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

import requests

if TYPE_CHECKING:  # avoid a runtime import cycle with llm_client
    from .llm_client import LLMProvider

logger = logging.getLogger(__name__)

#: Env var that points the terminal client at the deployed gateway's
#: OpenAI-compatible ``base_url``. Unset ⇒ the seam is inert (direct path).
GATEWAY_BASE_URL_ENV = "OPEN_TOLKEIN_BASE_URL"
#: Env var pinning the gateway contract version the monorepo expects (§7.2).
#: Recorded in the route note; compatibility enforcement is a follow-up slice.
GATEWAY_CONTRACT_ENV = "OPEN_TOLKEIN_CONTRACT_VERSION"
#: Env vars seeding :class:`RoutePolicy` (§3.3). All optional, fail-safe.
GATEWAY_LOCALITY_ENV = "OPEN_TOLKEIN_LOCALITY"
GATEWAY_CACHE_MODE_ENV = "OPEN_TOLKEIN_CACHE_MODE"
GATEWAY_COST_CEILING_ENV = "OPEN_TOLKEIN_COST_CEILING"
#: Env var overriding the reachability-probe timeout (seconds).
GATEWAY_PROBE_TIMEOUT_ENV = "OPEN_TOLKEIN_PROBE_TIMEOUT"

#: Non-secret placeholder bearer token for the gateway client. The gateway is
#: key-free from the monorepo's side (#275); OpenAIClient only requires a
#: non-empty token, so a constant satisfies it without reading any real key —
#: exactly the ``"EMPTY"`` shape the local ``vllm`` path already uses.
GATEWAY_PLACEHOLDER_TOKEN = "open-tolkein"

#: Default reachability-probe timeout (seconds). Short so a down gateway is
#: detected fast and the run falls back to the direct path without stalling.
_DEFAULT_PROBE_TIMEOUT = 3.0


class Locality(str, Enum):
    """Per-request locality preference (RFC-012 §3.3/§3.4)."""

    LOCAL_ONLY = "local_only"
    PREFER_LOCAL = "prefer_local"
    ANY = "any"

    @classmethod
    def from_str(cls, value: str) -> Optional["Locality"]:
        try:
            return cls(value.strip().lower())
        except ValueError:
            return None


@dataclass(frozen=True)
class RoutePolicy:
    """The three routing knobs the gateway honors (RFC-012 §3.3) — and only three.

    * ``locality`` — ``local_only`` · ``prefer_local`` (default) · ``any`` (§3.4).
    * ``cache_mode`` — ``None`` inherits the run's :class:`~rfc.answer_cache.CacheMode`
      (#317); an explicit string pins it over the gateway boundary.
    * ``cost_ceiling`` — projected per-request USD budget; ``0.0`` means unlimited.
    """

    locality: Locality = Locality.PREFER_LOCAL
    cache_mode: Optional[str] = None
    cost_ceiling: float = 0.0

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "RoutePolicy":
        """Seed a policy from the environment, failing safe to the defaults."""
        env = os.environ if env is None else env

        locality = Locality.PREFER_LOCAL
        raw_locality = env.get(GATEWAY_LOCALITY_ENV, "").strip()
        if raw_locality:
            parsed = Locality.from_str(raw_locality)
            if parsed is not None:
                locality = parsed
            else:
                logger.warning(
                    "%s=%r is not a recognized locality (expected local_only, "
                    "prefer_local, or any); using %s.",
                    GATEWAY_LOCALITY_ENV,
                    raw_locality,
                    locality.value,
                )

        cache_mode = env.get(GATEWAY_CACHE_MODE_ENV, "").strip() or None

        cost_ceiling = 0.0
        raw_ceiling = env.get(GATEWAY_COST_CEILING_ENV, "").strip()
        if raw_ceiling:
            try:
                cost_ceiling = max(0.0, float(raw_ceiling))
            except ValueError:
                logger.warning(
                    "%s=%r is not a number; using unlimited (0).",
                    GATEWAY_COST_CEILING_ENV,
                    raw_ceiling,
                )

        return cls(locality=locality, cache_mode=cache_mode, cost_ceiling=cost_ceiling)


@dataclass(frozen=True)
class RouteDecision:
    """The outcome of :func:`select_backend` for one provider creation."""

    #: True ⇒ build the gateway client; False ⇒ use the direct provider path.
    via_gateway: bool
    base_url: Optional[str]
    contract_version: Optional[str]
    policy: RoutePolicy
    #: Machine-readable tag: ``gateway-not-configured`` / ``gateway-selected`` /
    #: ``gateway-unreachable-fallback``.
    reason: str
    #: Human-readable route note (already logged at the appropriate level).
    note: str


#: A reachability probe: ``(base_url, timeout_seconds) -> reachable``.
ProbeFn = Callable[[str, float], bool]


def _probe_timeout(env: Mapping[str, str]) -> float:
    raw = env.get(GATEWAY_PROBE_TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_PROBE_TIMEOUT
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_PROBE_TIMEOUT


def probe_gateway(base_url: str, timeout: float = _DEFAULT_PROBE_TIMEOUT) -> bool:
    """Return whether the gateway process answers on ``base_url``.

    A lightweight GET of the OpenAI-compatible ``/models`` endpoint. *Any* HTTP
    response below 500 counts as reachable (a 4xx means the gateway is up, merely
    rejecting the request); a connection error, timeout, or 5xx counts as
    unreachable. Never raises — a probe failure is the skip-and-log signal, not
    an error that could fail a run.
    """
    url = base_url.rstrip("/") + "/models"
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {GATEWAY_PLACEHOLDER_TOKEN}"},
        )
    except requests.RequestException as exc:
        logger.debug("open-tolkein probe of %s failed: %s", url, exc)
        return False
    return resp.status_code < 500


def select_backend(
    provider: str = "",
    *,
    policy: Optional[RoutePolicy] = None,
    env: Optional[Mapping[str, str]] = None,
    probe: Optional[ProbeFn] = None,
) -> RouteDecision:
    """Decide how this request routes — the one routing decision (RFC-012 MS1).

    Args:
        provider: The direct provider name this call would otherwise build
            (``"ollama"`` / ``"openai"`` / ``"vllm"``) — used only for log text.
        policy: The :class:`RoutePolicy` to record; defaults to
            :meth:`RoutePolicy.from_env`.
        env: Environment mapping (defaults to ``os.environ``) — injectable for
            hermetic tests.
        probe: Reachability probe (defaults to :func:`probe_gateway`) —
            injectable so tests need no real socket.

    Returns:
        A :class:`RouteDecision`. ``via_gateway`` is True only when
        ``OPEN_TOLKEIN_BASE_URL`` is set *and* the gateway is reachable;
        otherwise the direct provider path is used (inert seam, or skip-and-log
        fallback on a down gateway).
    """
    env = os.environ if env is None else env
    policy = policy or RoutePolicy.from_env(env)
    base_url = env.get(GATEWAY_BASE_URL_ENV, "").strip().rstrip("/")
    contract = env.get(GATEWAY_CONTRACT_ENV, "").strip() or None
    label = repr(provider) if provider else "(default)"

    if not base_url:
        note = (
            f"open-tolkein seam inert: {GATEWAY_BASE_URL_ENV} unset; "
            f"routing direct to provider {label}."
        )
        logger.debug(note)
        return RouteDecision(
            via_gateway=False,
            base_url=None,
            contract_version=contract,
            policy=policy,
            reason="gateway-not-configured",
            note=note,
        )

    probe = probe or probe_gateway
    if probe(base_url, _probe_timeout(env)):
        pin = f" (contract {contract})" if contract else ""
        note = f"open-tolkein seam active: routing {label} via gateway {base_url}{pin}."
        logger.info(note)
        return RouteDecision(
            via_gateway=True,
            base_url=base_url,
            contract_version=contract,
            policy=policy,
            reason="gateway-selected",
            note=note,
        )

    note = (
        f"open-tolkein gateway at {base_url} is unreachable; skip-and-log — "
        f"falling back to the direct provider path for {label}. A down gateway "
        f"must never fail a cached/local run (RFC-012 §7.2)."
    )
    logger.warning(note)
    return RouteDecision(
        via_gateway=False,
        base_url=None,
        contract_version=contract,
        policy=policy,
        reason="gateway-unreachable-fallback",
        note=note,
    )


class _GatewayProvenanceProvider:
    """Transparent proxy recording the open-tolkein route note into ``last_metrics``.

    MS1 threads only what is honestly available — that the terminal client is the
    gateway, its ``base_url``, and the pinned contract version — into the existing
    per-call metadata path (``last_metrics``), which the spine already serializes
    via ``emit_rfc_data("llm_metrics", ...)``. If the gateway surfaces richer
    provenance under a ``route`` key, it is preserved. Per-hop cost/latency/
    compute and the RFC-008 ``served_by`` column are MS5 (#328).
    """

    def __init__(
        self,
        inner: "LLMProvider",
        *,
        base_url: str,
        contract_version: Optional[str] = None,
    ) -> None:
        self.__wrapped__ = inner
        note: dict[str, Any] = {"served_via": "open-tolkein", "base_url": base_url}
        if contract_version:
            note["contract_version"] = contract_version
        self._route_note = note

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__wrapped__, name)

    def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        text = self.__wrapped__.generate(prompt, *args, **kwargs)
        metrics = getattr(self.__wrapped__, "last_metrics", None)
        if not isinstance(metrics, dict):
            metrics = {}
            self.__wrapped__.last_metrics = metrics
        existing = metrics.get("route")
        note = dict(self._route_note)
        if isinstance(existing, dict):
            # Gateway-surfaced provenance wins on key collisions; the seam only
            # fills what the gateway did not report (never fabricates numbers).
            note.update(existing)
        metrics["route"] = note
        return text


def build_gateway_client(
    base_url: str,
    *,
    contract_version: Optional[str] = None,
    **kwargs: Any,
) -> "LLMProvider":
    """Build the key-free terminal client pointing at the gateway ``base_url``.

    The client is an :class:`~rfc.openai_client.OpenAIClient` (the gateway speaks
    the OpenAI-compatible API) built with the constant, non-secret
    :data:`GATEWAY_PLACEHOLDER_TOKEN` — **no** ``*_API_KEY`` env var is read here.
    It is wrapped in :class:`_GatewayProvenanceProvider` so the route note lands
    in ``last_metrics``.
    """
    from .openai_client import OpenAIClient

    # The seam owns base_url/api_key; drop any caller-supplied overrides so the
    # key-free invariant cannot be subverted by a stray kwarg.
    kwargs.pop("base_url", None)
    kwargs.pop("api_key", None)

    inner = OpenAIClient(base_url=base_url, api_key=GATEWAY_PLACEHOLDER_TOKEN, **kwargs)
    return _GatewayProvenanceProvider(
        inner, base_url=base_url, contract_version=contract_version
    )


__all__ = [
    "GATEWAY_BASE_URL_ENV",
    "GATEWAY_CONTRACT_ENV",
    "GATEWAY_PLACEHOLDER_TOKEN",
    "Locality",
    "RouteDecision",
    "RoutePolicy",
    "build_gateway_client",
    "probe_gateway",
    "select_backend",
]
