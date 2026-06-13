"""External OpenAI-compatible provider configuration and discovery (issue #507).

Providers (OpenRouter, Groq, Cerebras, ...) are remote OpenAI-compatible
APIs declared under a ``providers:`` list in ``config/local_models.yaml``::

    providers:
      - name: openrouter
        base_url: https://openrouter.ai/api/v1
        api_key_env: OPENROUTER_API_KEY
        discover_free_pool: true
        models: []                      # optional static model ids
        max_requests_per_day: 1000      # free-pool daily budget
        requests_per_minute: 20         # free-pool rate limit
        requests_per_suite_estimate: 15 # ~calls one suite run makes
        max_context_tokens: 8192        # 0 = unlimited; bigger suites skip

Requests are served by the existing :class:`rfc.openai_client.OpenAIClient`
(via ``LLM_PROVIDER=openai``) — no provider-specific client exists or should.
A provider whose API key env var is unset is skipped with a log line
(CLAUDE.md skip-and-log), so the feature is inert without credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

#: Default OpenRouter free-pool budget: 1,000 requests/day after the
#: one-time $10 credit unlock, at 20 requests/minute.
DEFAULT_MAX_REQUESTS_PER_DAY = 1000
DEFAULT_REQUESTS_PER_MINUTE = 20
#: Rough number of LLM calls one (model, suite) run makes — issue #507
#: measured ~13 tests/suite; 15 leaves headroom for retries.
DEFAULT_REQUESTS_PER_SUITE_ESTIMATE = 15

_DISCOVERY_TIMEOUT = 30


@dataclass(frozen=True)
class ProviderConfig:
    """One external OpenAI-compatible API provider."""

    name: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...] = ()
    discover_free_pool: bool = False
    max_requests_per_day: int = DEFAULT_MAX_REQUESTS_PER_DAY
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    requests_per_suite_estimate: int = DEFAULT_REQUESTS_PER_SUITE_ESTIMATE
    #: Provider-wide context window cap in tokens; 0 means unlimited.
    #: Suites declaring a larger ``min_context_tokens`` are skipped (#509).
    max_context_tokens: int = 0


def load_providers(config: dict[str, Any]) -> list[ProviderConfig]:
    """Parse the ``providers:`` section of local_models.yaml.

    Args:
        config: Parsed local_models.yaml dict.

    Returns:
        One :class:`ProviderConfig` per entry; ``[]`` when the section is
        absent or empty.

    Raises:
        ValueError: If ``providers`` is not a list, or an entry is missing
            one of the required keys (``name``, ``base_url``, ``api_key_env``).
    """
    raw = config.get("providers") or []
    if not isinstance(raw, list):
        raise ValueError(
            f"'providers' must be a list of provider entries, got {type(raw).__name__}"
        )

    providers: list[ProviderConfig] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"providers[{i}] must be a mapping, got {entry!r}")
        for key in ("name", "base_url", "api_key_env"):
            if not entry.get(key):
                raise ValueError(f"providers[{i}] is missing required key '{key}'")
        providers.append(
            ProviderConfig(
                name=str(entry["name"]),
                base_url=str(entry["base_url"]).rstrip("/"),
                api_key_env=str(entry["api_key_env"]),
                models=tuple(entry.get("models") or ()),
                discover_free_pool=bool(entry.get("discover_free_pool", False)),
                max_requests_per_day=int(
                    entry.get("max_requests_per_day", DEFAULT_MAX_REQUESTS_PER_DAY)
                ),
                requests_per_minute=int(
                    entry.get("requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE)
                ),
                requests_per_suite_estimate=int(
                    entry.get(
                        "requests_per_suite_estimate",
                        DEFAULT_REQUESTS_PER_SUITE_ESTIMATE,
                    )
                ),
                max_context_tokens=int(entry.get("max_context_tokens", 0)),
            )
        )
    return providers


def resolve_api_key(provider: ProviderConfig) -> str | None:
    """Return the provider's API key from its env var, or None when absent.

    A blank/whitespace value counts as absent so a commented-out
    ``OPENROUTER_API_KEY=`` line in ``.env`` behaves like no key at all.
    """
    key = os.environ.get(provider.api_key_env, "").strip()
    return key or None


def discover_free_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float = _DISCOVERY_TIMEOUT,
) -> list[str]:
    """Fetch the provider's model catalog and return free-pool model ids.

    Queries ``{base_url}/models`` (OpenRouter-compatible schema:
    ``{"data": [{"id": ...}, ...]}``) and keeps ids ending in ``:free``.
    The free pool churns, so ids are discovered at run time — never
    hardcoded (issue #507).

    Raises:
        requests.RequestException: On network/HTTP failure — callers apply
            skip-and-log.
    """
    response = requests.get(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    free: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if isinstance(model_id, str) and model_id.endswith(":free"):
            free.append(model_id)
    return free


def select_models_within_budget(
    models: list[str],
    n_suites: int,
    *,
    max_requests_per_day: int,
    requests_per_suite_estimate: int,
) -> list[str]:
    """Keep the longest model prefix whose estimated requests fit the budget.

    Each model is estimated to cost ``n_suites * requests_per_suite_estimate``
    requests for a full sweep. Order is preserved; models that would push the
    daily total past ``max_requests_per_day`` are dropped from the tail.
    """
    cost_per_model = n_suites * requests_per_suite_estimate
    kept: list[str] = []
    spent = 0
    for model in models:
        if spent + cost_per_model > max_requests_per_day:
            break
        kept.append(model)
        spent += cost_per_model
    return kept


__all__ = [
    "ProviderConfig",
    "discover_free_models",
    "load_providers",
    "resolve_api_key",
    "select_models_within_budget",
]
