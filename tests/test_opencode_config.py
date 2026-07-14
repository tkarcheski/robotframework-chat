"""Shape guard for the repo ``core/opencode.json``.

Issue #191: the file the ``OpenCodeAdapter`` reuses (exported as
``OPENCODE_CONFIG``) must be *self-contained* — carry the local-Ollama transport
wiring itself rather than lean on a user's global opencode config — and must
carry **no external egress** (it ships publicly in ``core/``). These tests lock
both invariants so the file cannot silently regress to the pre-#191 state (an
``ollama`` provider with no ``npm``/``baseURL`` transport, plus an external
``openrouter`` provider).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "opencode.json"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


@pytest.fixture(scope="module")
def config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def _provider_base_urls(config: dict) -> list[str]:
    urls: list[str] = []
    for provider in (config.get("provider") or {}).values():
        base = (provider.get("options") or {}).get("baseURL")
        if isinstance(base, str) and base:
            urls.append(base)
    return urls


def test_is_valid_json_with_schema(config: dict) -> None:
    assert config["$schema"] == "https://opencode.ai/config.json"


def test_ollama_provider_has_transport_wiring(config: dict) -> None:
    ollama = config["provider"]["ollama"]
    # npm provider package + OpenAI-compatible baseURL make the file drive local
    # Ollama standalone (no reliance on a user's global config).
    assert ollama["npm"] == "@ai-sdk/openai-compatible"
    base = ollama["options"]["baseURL"]
    assert urlparse(base).hostname in _LOCAL_HOSTS
    assert ollama["models"], "ollama provider must list at least one model"


def test_default_model_points_at_a_declared_ollama_model(config: dict) -> None:
    model = config["model"]
    assert model.startswith("ollama/"), "default model must use the ollama provider"
    model_id = model.split("/", 1)[1]
    assert model_id in config["provider"]["ollama"]["models"]


def test_no_external_egress_provider(config: dict) -> None:
    # #191 scope: the public file carries no external-egress provider. Only the
    # local ollama provider is allowed, and every declared baseURL is localhost.
    assert set(config["provider"]) == {"ollama"}
    assert "openrouter" not in config["provider"]
    for base in _provider_base_urls(config):
        assert urlparse(base).hostname in _LOCAL_HOSTS, base


def test_carries_no_secret_material(config: dict) -> None:
    # A public config must never carry an inline credential.
    blob = json.dumps(config).lower()
    for needle in ("apikey", "api_key", "authorization", "sk-", "secret", "token"):
        assert needle not in blob, f"opencode.json must not carry {needle!r}"


def _iter_strings(node: object) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_strings(key)
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_strings(item)


def test_every_url_in_file_is_local_except_schema(config: dict) -> None:
    # File-wide egress guard (#191): a URL anywhere in the config — an ``mcp``
    # block, per-model options, custom headers — is an egress vector, not just
    # ``provider.options.baseURL``. Only the JSON-schema reference may point
    # off-localhost.
    body = {key: value for key, value in config.items() if key != "$schema"}
    for value in _iter_strings(body):
        for url in re.findall(r"https?://[^\s\"']+", value):
            assert urlparse(url).hostname in _LOCAL_HOSTS, url
