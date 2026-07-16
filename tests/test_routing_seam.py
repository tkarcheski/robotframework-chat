"""Tests for the open-tolkein consumption seam (RFC-012 MS1, #324).

Hermetic throughout: a stdlib fake gateway (real localhost HTTP) exercises the
end-to-end routed path and the reachability probe over a real socket; the
inert-seam, skip-and-log-fallback, and key-free paths use injected probes / a
recording environment so no network is required.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import logging
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

import rfc.routing as routing
from rfc.llm_client import create_provider, unwrap_provider
from rfc.ollama import OllamaClient
from rfc.openai_client import OpenAIClient
from rfc.routing import (
    GATEWAY_PLACEHOLDER_TOKEN,
    Locality,
    LocalOnlyEgressError,
    RouteDecision,
    RoutePolicy,
    build_gateway_client,
    probe_gateway,
    select_backend,
)

# --- constants ---------------------------------------------------------------

_ROUTED_ANSWER = "routed via the gateway"
# BYOK key env vars that must NEVER be read on the monorepo side (#275, §5.2).
_FORBIDDEN_KEY_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "VLLM_API_KEY",
)


# --- fake gateway (real localhost HTTP) --------------------------------------


class _FakeGatewayHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible gateway: /models (probe) + /chat/completions."""

    def _json(self, code: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"data": [{"id": "gw-model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # drain the request body
        if self.path.endswith("/chat/completions"):
            self._json(
                200,
                {
                    "choices": [{"message": {"content": _ROUTED_ANSWER}}],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                },
            )
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *args: Any) -> None:  # silence the test server
        return


@pytest.fixture()
def fake_gateway() -> Iterator[str]:
    """Start a real localhost gateway on an ephemeral port; yield its base_url."""
    server = HTTPServer(("127.0.0.1", 0), _FakeGatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _clean_seam_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every seam / wrapper env var so each test starts from the defaults."""
    for var in (
        routing.GATEWAY_BASE_URL_ENV,
        routing.GATEWAY_CONTRACT_ENV,
        routing.GATEWAY_LOCALITY_ENV,
        routing.GATEWAY_CACHE_MODE_ENV,
        routing.GATEWAY_COST_CEILING_ENV,
        routing.GATEWAY_PROBE_TIMEOUT_ENV,
        "ANSWER_CACHE_ENABLED",
        "GRAYLOG_LLM_ENABLED",
        "LLM_CONSOLE_FEED_ENABLED",
        "RFC_RUN_MODE",
        "LLM_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)


# --- RoutePolicy -------------------------------------------------------------


class TestRoutePolicy:
    def test_defaults_match_rfc_3_3(self) -> None:
        policy = RoutePolicy()
        assert policy.locality is Locality.PREFER_LOCAL
        assert policy.cache_mode is None  # inherit CacheMode (#317)
        assert policy.cost_ceiling == 0.0  # unlimited

    def test_from_env_parses_all_knobs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(routing.GATEWAY_LOCALITY_ENV, "local_only")
        monkeypatch.setenv(routing.GATEWAY_CACHE_MODE_ENV, "exact_only")
        monkeypatch.setenv(routing.GATEWAY_COST_CEILING_ENV, "0.25")
        policy = RoutePolicy.from_env()
        assert policy.locality is Locality.LOCAL_ONLY
        assert policy.cache_mode == "exact_only"
        assert policy.cost_ceiling == 0.25

    def test_from_env_fails_safe_on_bad_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(routing.GATEWAY_LOCALITY_ENV, "sideways")
        monkeypatch.setenv(routing.GATEWAY_COST_CEILING_ENV, "not-a-number")
        policy = RoutePolicy.from_env()
        assert policy.locality is Locality.PREFER_LOCAL  # fell back to default
        assert policy.cost_ceiling == 0.0

    def test_is_frozen(self) -> None:
        policy = RoutePolicy()
        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.locality = Locality.ANY  # type: ignore[misc]


# --- select_backend ----------------------------------------------------------


class TestSelectBackend:
    def test_inert_when_base_url_unset(self) -> None:
        decision = select_backend("ollama")
        assert decision.via_gateway is False
        assert decision.base_url is None
        assert decision.reason == "gateway-not-configured"

    def test_selects_gateway_when_configured_and_reachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        decision = select_backend("ollama", probe=lambda url, timeout: True)
        assert decision.via_gateway is True
        assert decision.base_url == "http://gw.local/v1"
        assert decision.reason == "gateway-selected"

    def test_skip_and_log_fallback_when_unreachable(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        with caplog.at_level(logging.WARNING, logger="rfc.routing"):
            decision = select_backend("ollama", probe=lambda url, timeout: False)
        assert decision.via_gateway is False  # fall back to the direct path
        assert decision.base_url is None
        assert decision.reason == "gateway-unreachable-fallback"
        assert any("unreachable" in r.message for r in caplog.records)

    def test_contract_version_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        monkeypatch.setenv(routing.GATEWAY_CONTRACT_ENV, "v0.3")
        decision = select_backend("ollama", probe=lambda url, timeout: True)
        assert decision.contract_version == "v0.3"

    def test_trailing_slash_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1/")
        decision = select_backend("ollama", probe=lambda url, timeout: True)
        assert decision.base_url == "http://gw.local/v1"

    def test_returns_route_decision_type(self) -> None:
        assert isinstance(select_backend("ollama"), RouteDecision)


# --- probe_gateway (real socket) ---------------------------------------------


class TestProbeGateway:
    def test_reachable_gateway_probes_true(self, fake_gateway: str) -> None:
        assert probe_gateway(fake_gateway) is True

    def test_down_gateway_probes_false_without_raising(self) -> None:
        # Nothing is listening on this port; the probe must return False, not raise.
        assert probe_gateway("http://127.0.0.1:1/v1", timeout=0.5) is False


# --- create_provider integration ---------------------------------------------


class TestCreateProviderSeam:
    def test_inert_seam_returns_direct_ollama(self) -> None:
        """No OPEN_TOLKEIN_BASE_URL ⇒ behavior is byte-for-byte the old path."""
        client = create_provider(provider="ollama", model="test-model")
        assert isinstance(unwrap_provider(client), OllamaClient)

    def test_routes_through_gateway_end_to_end(
        self, fake_gateway: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, fake_gateway)
        monkeypatch.setenv(routing.GATEWAY_CONTRACT_ENV, "v0.1")
        client = create_provider(provider="ollama", model="gw-model")

        concrete = unwrap_provider(client)
        assert isinstance(concrete, OpenAIClient)
        assert concrete.base_url == fake_gateway
        assert concrete.api_key == GATEWAY_PLACEHOLDER_TOKEN  # key-free placeholder

        answer = client.generate("who is Tom Bombadil?")
        assert answer == _ROUTED_ANSWER

        # Route provenance landed in the existing last_metrics metadata path.
        route = client.last_metrics["route"]
        assert route["served_via"] == "open-tolkein"
        assert route["base_url"] == fake_gateway
        assert route["contract_version"] == "v0.1"

    def test_down_gateway_falls_back_to_direct(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A configured-but-down gateway must not fail the run — fall back direct."""
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://127.0.0.1:1/v1")
        monkeypatch.setenv(routing.GATEWAY_PROBE_TIMEOUT_ENV, "0.5")
        with caplog.at_level(logging.WARNING, logger="rfc.routing"):
            client = create_provider(provider="ollama", model="test-model")
        assert isinstance(unwrap_provider(client), OllamaClient)
        assert any("unreachable" in r.message for r in caplog.records)

    def test_gateway_path_does_not_require_openai_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM_PROVIDER=openai + no OPENAI_API_KEY still works via the gateway.

        Proves the decide-before-build ordering: a gateway-routed run never
        forces the direct provider's key (#275).
        """
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(routing, "probe_gateway", lambda url, timeout: True)
        client = create_provider(model="gw-model")  # must not raise
        assert isinstance(unwrap_provider(client), OpenAIClient)


# --- key-free by construction (#275, §5.2) -----------------------------------


class _RecordingEnv(dict):
    """A dict that records every key looked up — a runtime env-access spy."""

    def __init__(self, base: dict[str, str]) -> None:
        super().__init__(base)
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        self.reads.append(key)
        return super().get(key, default)

    def __contains__(self, key: object) -> bool:
        self.reads.append(str(key))
        return super().__contains__(key)


class TestKeyFree:
    def test_no_api_key_env_read_on_gateway_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Grep-proof, at runtime: routing to the gateway reads no *_API_KEY.

        Every forbidden key is present in the environment, yet the gateway path
        must not touch one — the gateway holds the keys, this side never does.
        """
        base = {
            routing.GATEWAY_BASE_URL_ENV: "http://gw.local/v1",
            **{var: "sk-must-not-be-read" for var in _FORBIDDEN_KEY_VARS},
        }
        spy = _RecordingEnv(base)
        monkeypatch.setattr(os, "environ", spy)
        monkeypatch.setattr(routing, "probe_gateway", lambda url, timeout: True)

        client = create_provider(provider="openai", model="gw-model")
        assert isinstance(unwrap_provider(client), OpenAIClient)

        leaked = [k for k in spy.reads if k in _FORBIDDEN_KEY_VARS]
        assert leaked == [], f"gateway path read forbidden key env var(s): {leaked}"

    def test_source_reads_no_api_key_env_var(self) -> None:
        """Static backstop: the seam never *reads* a ``*_API_KEY`` env var.

        Parses the module and collects the string arguments of every env access
        (``os.getenv(...)``, ``os.environ.get(...)``, ``os.environ[...]``); none
        may name a key var. Prose in docstrings mentioning ``*_API_KEY`` is
        intentionally not flagged — only real env reads are.
        """
        with open(routing.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        env_read_args: list[str] = []
        for node in ast.walk(tree):
            # os.getenv("X") / os.environ.get("X")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"getenv", "get"} and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        env_read_args.append(arg.value)
            # os.environ["X"]
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                if isinstance(node.slice.value, str):
                    env_read_args.append(node.slice.value)

        leaked = [a for a in env_read_args if "API_KEY" in a]
        assert leaked == [], f"seam reads key env var(s): {leaked}"

    def test_gateway_client_uses_constant_placeholder_token(self) -> None:
        client = build_gateway_client("http://gw.local/v1")
        assert unwrap_provider(client).api_key == GATEWAY_PLACEHOLDER_TOKEN


# --- provenance capture ------------------------------------------------------


class _FakeInner:
    """A minimal LLMProvider stand-in that records the prompt and sets metrics."""

    def __init__(self, metrics: dict[str, Any] | None = None) -> None:
        self.last_metrics = metrics
        self.model = "fake"

    def generate(self, prompt: str) -> str:
        if self.last_metrics is None:
            self.last_metrics = {}
        self.last_metrics["prompt_tokens"] = 7
        return "ok"


class TestProvenanceCapture:
    def test_route_note_added_to_last_metrics(self) -> None:
        wrapper = routing._GatewayProvenanceProvider(
            _FakeInner({"prompt_tokens": 0}),
            base_url="http://gw.local/v1",
            contract_version="v9",
        )
        wrapper.generate("hi")
        route = wrapper.last_metrics["route"]
        assert route == {
            "served_via": "open-tolkein",
            "base_url": "http://gw.local/v1",
            "contract_version": "v9",
        }

    def test_gateway_surfaced_route_is_preserved(self) -> None:
        """If the gateway already surfaced provenance, the seam preserves it."""
        inner = _FakeInner({"route": {"served_by": "ollama:ai1", "tier_order": 2}})
        wrapper = routing._GatewayProvenanceProvider(
            inner, base_url="http://gw.local/v1"
        )
        wrapper.generate("hi")
        route = wrapper.last_metrics["route"]
        assert route["served_by"] == "ollama:ai1"  # gateway detail kept
        assert route["tier_order"] == 2
        assert route["served_via"] == "open-tolkein"  # seam fact added

    def test_handles_none_last_metrics(self) -> None:
        wrapper = routing._GatewayProvenanceProvider(
            _FakeInner(None), base_url="http://gw.local/v1"
        )
        wrapper.generate("hi")
        assert wrapper.last_metrics["route"]["served_via"] == "open-tolkein"


# --- inert seam: byte-for-byte the OLD direct path, every provider -----------
# (test-design: the engineer's inertness claim was asserted only for ollama; a
# subtle regression that hijacked openai/vllm — or leaked the gateway placeholder
# token into a direct client — would slip a single-provider check. This is the
# full §1.1 env matrix with OPEN_TOLKEIN_BASE_URL UNSET.)


class TestInertSeamMatrix:
    def test_inert_openai_without_key_still_raises_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Seam unset + openai + no key ⇒ the historical direct-path error,
        NOT a silent gateway detour that would mask a missing key (#275 inverse)."""
        from rfc.exceptions import MissingProviderConfigError

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(MissingProviderConfigError):
            create_provider(provider="openai", model="m")

    def test_inert_openai_with_key_uses_that_key_not_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The direct openai client carries the REAL key — the seam did not
        swap in the gateway placeholder when it is inert."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-direct-key")
        inner = unwrap_provider(create_provider(provider="openai", model="m"))
        assert isinstance(inner, OpenAIClient)
        assert inner.api_key == "sk-real-direct-key"
        assert inner.api_key != GATEWAY_PLACEHOLDER_TOKEN

    def test_inert_vllm_uses_empty_token_and_vllm_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """vllm keeps its own ``EMPTY`` precedent and localhost base_url — the
        seam did not reroute it or overwrite its token/endpoint."""
        monkeypatch.delenv("VLLM_BASE_URL", raising=False)
        monkeypatch.delenv("VLLM_API_KEY", raising=False)
        inner = unwrap_provider(create_provider(provider="vllm", model="m"))
        assert isinstance(inner, OpenAIClient)
        assert inner.api_key == "EMPTY"
        assert inner.api_key != GATEWAY_PLACEHOLDER_TOKEN
        assert inner.base_url == "http://localhost:8000/v1"

    def test_inert_ollama_unchanged(self) -> None:
        assert isinstance(
            unwrap_provider(create_provider(provider="ollama", model="m")),
            OllamaClient,
        )

    def test_empty_base_url_is_inert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty (not merely unset) OPEN_TOLKEIN_BASE_URL is still inert —
        a blank export must never flip the seam on."""
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "   ")
        assert select_backend("ollama").reason == "gateway-not-configured"
        assert isinstance(
            unwrap_provider(create_provider(provider="ollama", model="m")),
            OllamaClient,
        )


# --- §7.2: a down gateway must NEVER fail a cached/local run -----------------
# (test-design: the engineer's down-gateway test proved only that create_provider
# falls back to the direct client without raising. The load-bearing §7.2 promise
# — the local replay tape STILL serves when the gateway is down — was untested at
# the seam. Here the direct backend is booby-trapped to explode on any live call,
# so a served answer proves the run came purely from the cache in front of the
# down-gateway fallback.)


class TestDownGatewayNeverFailsCachedRun:
    def test_down_gateway_cache_only_hit_serves_from_tape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakeredis = pytest.importorskip("fakeredis")
        from rfc.answer_cache import AnswerCache, CacheMode

        shared = fakeredis.FakeStrictRedis()
        monkeypatch.setattr(
            AnswerCache,
            "from_env",
            classmethod(lambda cls: AnswerCache(redis_client=shared)),
        )

        # Gateway configured but DOWN (nothing listens on port 1); short probe.
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://127.0.0.1:1/v1")
        monkeypatch.setenv(routing.GATEWAY_PROBE_TIMEOUT_ENV, "0.5")
        # Force the answer-cache ON in CACHE_ONLY — the CI replay tape (#259).
        monkeypatch.setenv("ANSWER_CACHE_ENABLED", "1")
        monkeypatch.setenv("RFC_RUN_MODE", "replay")

        # Any live backend call under a down gateway is a §7.2 violation.
        def _boom(self: Any, prompt: str) -> str:
            raise AssertionError(
                "a down gateway forced a live backend call — §7.2 violated"
            )

        monkeypatch.setattr(OllamaClient, "generate", _boom)

        prompt = "who is Tom Bombadil?"
        client = create_provider(provider="ollama", model="test-model")

        # The cache sits in FRONT of the down-gateway fallback (never bypassed).
        assert client.cache_mode is CacheMode.CACHE_ONLY
        inner = unwrap_provider(client)
        assert isinstance(inner, OllamaClient)  # fell back to the direct path

        # Seed the replay tape for this exact client/prompt on the shared store.
        seed = AnswerCache(redis_client=shared)
        seed.set(seed.make_key(inner, prompt), "replayed: Tom Bombadil")

        # The cached run serves from the tape — the down gateway never fails it,
        # and the booby-trapped live backend is never called.
        assert client.generate(prompt) == "replayed: Tom Bombadil"


# --- §3.4: a down-gateway fallback must FAIL CLOSED under local_only ----------
# (Tusk's #326 blocking note: the MS1 seam ships a down-gateway fallback that,
# for locality=local_only + a remote direct provider + a cache miss, builds a
# remote client and leaves the fleet boundary — the one seam line that can egress
# a local_only prompt. MS3 closes it: the fallback refuses loudly rather than
# downgrading a no-egress request to a remote BYOK path. These tests pin exactly
# that path — the down-gateway fallback, not the up-path passthrough — alongside
# the allowed local-class fallbacks and the untouched non-local_only path.)


_LOCAL_ONLY = RoutePolicy(locality=Locality.LOCAL_ONLY)


class TestDownGatewayLocalOnlyFailsClosed:
    def test_local_only_remote_direct_fallback_refuses(self) -> None:
        """gateway down + local_only + remote direct config ⇒ typed refusal.

        The adversarial path Tusk pinned: never a silent egress on the fallback.
        """
        with pytest.raises(LocalOnlyEgressError, match="fleet boundary"):
            select_backend(
                "openai",
                policy=_LOCAL_ONLY,
                env={routing.GATEWAY_BASE_URL_ENV: "http://gw.local/v1"},
                probe=lambda url, timeout: False,
            )

    def test_local_only_unknown_provider_refuses(self) -> None:
        """Fail closed on the unknown: only proven localhost-class falls back."""
        with pytest.raises(LocalOnlyEgressError):
            select_backend(
                "some-remote-thing",
                policy=_LOCAL_ONLY,
                env={routing.GATEWAY_BASE_URL_ENV: "http://gw.local/v1"},
                probe=lambda url, timeout: False,
            )

    def test_local_only_ollama_direct_fallback_allowed(self) -> None:
        """gateway down + local_only + ollama (localhost-class) ⇒ allowed fall."""
        decision = select_backend(
            "ollama",
            policy=_LOCAL_ONLY,
            env={routing.GATEWAY_BASE_URL_ENV: "http://gw.local/v1"},
            probe=lambda url, timeout: False,
        )
        assert decision.via_gateway is False
        assert decision.reason == "gateway-unreachable-fallback"

    def test_local_only_vllm_direct_fallback_allowed(self) -> None:
        """vllm is a local tier (RFC-012 §3.2) — its fallback is allowed too."""
        decision = select_backend(
            "vllm",
            policy=_LOCAL_ONLY,
            env={routing.GATEWAY_BASE_URL_ENV: "http://gw.local/v1"},
            probe=lambda url, timeout: False,
        )
        assert decision.via_gateway is False
        assert decision.reason == "gateway-unreachable-fallback"

    def test_non_local_only_remote_direct_fallback_unchanged(self) -> None:
        """prefer_local (default) + remote direct + down gateway ⇒ still falls
        back exactly as before — the guard is scoped to local_only only."""
        decision = select_backend(
            "openai",
            policy=RoutePolicy(locality=Locality.PREFER_LOCAL),
            env={routing.GATEWAY_BASE_URL_ENV: "http://gw.local/v1"},
            probe=lambda url, timeout: False,
        )
        assert decision.via_gateway is False
        assert decision.reason == "gateway-unreachable-fallback"

    def test_local_only_reachable_gateway_not_refused(self) -> None:
        """A REACHABLE gateway routes local_only through itself (it owns the
        locality routing); the seam guard is only for the down-gateway fallback."""
        decision = select_backend(
            "openai",
            policy=_LOCAL_ONLY,
            env={routing.GATEWAY_BASE_URL_ENV: "http://gw.local/v1"},
            probe=lambda url, timeout: True,
        )
        assert decision.via_gateway is True
        assert decision.reason == "gateway-selected"

    def test_local_only_inert_seam_not_refused(self) -> None:
        """No gateway configured ⇒ the inert legacy direct path is unchanged.

        RoutePolicy is a gateway-boundary concept (RFC-012 §3.3): with no
        boundary, the pre-seam path runs byte-for-byte as before. Deliberately
        scoped — the fail-closed guard binds the down-gateway *fallback*, not the
        inert seam.
        """
        decision = select_backend(
            "openai",
            policy=_LOCAL_ONLY,
            env={},  # OPEN_TOLKEIN_BASE_URL unset
            probe=lambda url, timeout: False,
        )
        assert decision.via_gateway is False
        assert decision.reason == "gateway-not-configured"

    def test_create_provider_local_only_remote_direct_down_gateway_refuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end at the factory: a local_only run with a remote direct
        config and a down gateway refuses rather than building a remote client."""
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        monkeypatch.setenv(routing.GATEWAY_LOCALITY_ENV, "local_only")
        monkeypatch.setattr(routing, "probe_gateway", lambda url, timeout: False)
        with pytest.raises(LocalOnlyEgressError):
            create_provider(provider="openai", model="m")

    def test_create_provider_local_only_ollama_down_gateway_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The local-class fallback still serves a local_only run (no egress)."""
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        monkeypatch.setenv(routing.GATEWAY_LOCALITY_ENV, "local_only")
        monkeypatch.setattr(routing, "probe_gateway", lambda url, timeout: False)
        client = create_provider(provider="ollama", model="m")
        assert isinstance(unwrap_provider(client), OllamaClient)


# --- test-design (Mr. Meeseeks) adversarial layer on the fail-closed seam -----
# Meaner variants: prove the refusal is STRUCTURAL (never a silent skip) and
# happens BEFORE any client/network object is constructed; and pin the one
# cross-half hole the seam does not close.


class TestSeamRefusalIsStructural:
    def test_local_only_egress_error_is_not_a_skip_error(self) -> None:
        """The refusal must FAIL loudly, never silently skip. LocalOnlyEgressError
        is a hard RuntimeError and deliberately NOT an RFCSkipError — so the
        repo's skip-and-log default (for an unavailable optional dependency)
        can never swallow a locality-safety breach."""
        from rfc.exceptions import RFCSkipError

        assert issubclass(LocalOnlyEgressError, RuntimeError)
        assert not issubclass(LocalOnlyEgressError, RFCSkipError)
        # And an instance is not caught by an ``except RFCSkipError`` handler.
        with pytest.raises(LocalOnlyEgressError):
            try:
                raise LocalOnlyEgressError("breach")
            except RFCSkipError:  # pragma: no cover - must NOT catch
                pytest.fail("a locality breach was swallowed as a skip")

    def test_local_only_openai_refuses_before_any_client_is_built(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spy: on the refused path NO provider/network client is constructed —
        the raise happens in select_backend, before _create_direct_provider ever
        touches OpenAIClient/OllamaClient."""
        built: list[str] = []

        def _spy_openai(*_a: Any, **_k: Any) -> Any:
            built.append("openai")
            raise AssertionError("OpenAIClient must never be constructed")

        def _spy_ollama(*_a: Any, **_k: Any) -> Any:
            built.append("ollama")
            raise AssertionError("OllamaClient must never be constructed")

        # _create_direct_provider imports OpenAIClient locally from this module.
        monkeypatch.setattr("rfc.openai_client.OpenAIClient", _spy_openai)
        monkeypatch.setattr("rfc.llm_client.OllamaClient", _spy_ollama)
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        monkeypatch.setenv(routing.GATEWAY_LOCALITY_ENV, "local_only")
        monkeypatch.setattr(routing, "probe_gateway", lambda url, timeout: False)

        with pytest.raises(LocalOnlyEgressError):
            create_provider(provider="openai", model="m")
        assert built == []  # nothing was constructed — refused before the build


class TestCrossHalfSeamGapOllamaOffbox:
    """The one hole this seam does NOT close, pinned so it can never go silent.

    The seam classifies the down-gateway fallback by provider *class name*
    (``ollama``/``vllm`` = localhost-class), NOT by the resolved ``base_url``.
    But that URL is operator-configurable (``OLLAMA_ENDPOINT`` / ``VLLM_BASE_URL``
    / a ``base_url`` kwarg). So a local_only run + a down gateway + an ``ollama``
    endpoint pointed at a PUBLIC url egresses, unguarded — the same #2 label-trust
    the gateway half kills, but on the path where the gateway (which owns
    URL-derivation) is down and cannot help.

    This is a disclosed, medium-severity residual (needs a public-URL misconfig;
    the normal LAN-private fleet config is safe) tracked by monorepo #368. The
    test below encodes the DESIRED fail-closed behavior as xfail(strict): the
    suite stays green now and goes RED the moment #368 lands, forcing the fix to
    un-xfail it — so the boundary is explicit, never a silent composition lie.
    """

    def test_local_only_ollama_pointed_offbox_egresses_unguarded_TODAY(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Factual pin of the CURRENT boundary: the seam builds an ollama client
        aimed at a public URL under local_only (no refusal) — the disclosed gap
        (monorepo #368). Documents reality without blessing it as correct."""
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        monkeypatch.setenv(routing.GATEWAY_LOCALITY_ENV, "local_only")
        monkeypatch.setenv("OLLAMA_ENDPOINT", "http://api.evil.com")
        monkeypatch.setattr(routing, "probe_gateway", lambda url, timeout: False)

        # select_backend sees only the NAME "ollama" and allows the fallback.
        decision = select_backend("ollama", policy=_LOCAL_ONLY)
        assert decision.reason == "gateway-unreachable-fallback"
        # …and the built client is aimed off-box: a local_only prompt would leave.
        client = unwrap_provider(create_provider(provider="ollama", model="m"))
        assert isinstance(client, OllamaClient)
        assert client.base_url == "http://api.evil.com"  # the unguarded egress

    @pytest.mark.xfail(
        strict=True,
        reason="monorepo #368: seam trusts provider class name, not the resolved "
        "ollama/vllm base_url; a local_only + down-gateway + off-box OLLAMA_ENDPOINT "
        "still egresses. Closing #368 (URL-derived seam check) makes this xpass.",
    )
    def test_local_only_ollama_pointed_offbox_SHOULD_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The desired end-state (#368): a local_only run whose ollama endpoint
        resolves off the fleet must fail closed at the seam, not egress."""
        monkeypatch.setenv(routing.GATEWAY_BASE_URL_ENV, "http://gw.local/v1")
        monkeypatch.setenv(routing.GATEWAY_LOCALITY_ENV, "local_only")
        monkeypatch.setenv("OLLAMA_ENDPOINT", "http://api.evil.com")
        monkeypatch.setattr(routing, "probe_gateway", lambda url, timeout: False)
        with pytest.raises(LocalOnlyEgressError):
            create_provider(provider="ollama", model="m")
