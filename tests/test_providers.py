"""Tests for rfc.providers — external OpenAI-compatible providers (issue #507)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from rfc.providers import (
    ProviderConfig,
    discover_free_models,
    load_providers,
    resolve_api_key,
    select_models_within_budget,
)


def _openrouter_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    }
    entry.update(overrides)
    return entry


class TestLoadProviders:
    def test_empty_config_returns_no_providers(self) -> None:
        assert load_providers({}) == []
        assert load_providers({"providers": []}) == []

    def test_parses_openrouter_entry_with_defaults(self) -> None:
        providers = load_providers({"providers": [_openrouter_entry()]})
        assert len(providers) == 1
        p = providers[0]
        assert p.name == "openrouter"
        assert p.base_url == "https://openrouter.ai/api/v1"
        assert p.api_key_env == "OPENROUTER_API_KEY"
        assert p.models == ()
        assert p.discover_free_pool is False
        assert p.max_requests_per_day == 1000
        assert p.requests_per_minute == 20

    def test_parses_full_entry(self) -> None:
        entry = _openrouter_entry(
            models=["meta-llama/llama-3.3-70b-instruct:free"],
            discover_free_pool=True,
            max_requests_per_day=500,
            requests_per_minute=10,
            requests_per_suite_estimate=13,
        )
        p = load_providers({"providers": [entry]})[0]
        assert p.models == ("meta-llama/llama-3.3-70b-instruct:free",)
        assert p.discover_free_pool is True
        assert p.max_requests_per_day == 500
        assert p.requests_per_minute == 10
        assert p.requests_per_suite_estimate == 13

    @pytest.mark.parametrize("missing", ["name", "base_url", "api_key_env"])
    def test_missing_required_key_raises(self, missing: str) -> None:
        entry = _openrouter_entry()
        del entry[missing]
        with pytest.raises(ValueError, match=missing):
            load_providers({"providers": [entry]})

    def test_non_list_providers_raises(self) -> None:
        with pytest.raises(ValueError, match="providers"):
            load_providers({"providers": {"name": "openrouter"}})

    def test_trailing_slash_stripped_from_base_url(self) -> None:
        entry = _openrouter_entry(base_url="https://openrouter.ai/api/v1/")
        p = load_providers({"providers": [entry]})[0]
        assert p.base_url == "https://openrouter.ai/api/v1"


class TestResolveApiKey:
    def _provider(self) -> ProviderConfig:
        return load_providers({"providers": [_openrouter_entry()]})[0]

    def test_returns_key_when_set(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-abc"}):
            assert resolve_api_key(self._provider()) == "sk-or-abc"

    def test_returns_none_when_unset(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            assert resolve_api_key(self._provider()) is None

    def test_returns_none_when_blank(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "   "}):
            assert resolve_api_key(self._provider()) is None


class TestDiscoverFreeModels:
    def _models_payload(self) -> dict[str, object]:
        return {
            "data": [
                {"id": "meta-llama/llama-3.3-70b-instruct:free"},
                {"id": "openai/gpt-4o-mini"},
                {"id": "qwen/qwen3-32b:free"},
                {"id": "deepseek/deepseek-r1"},
            ]
        }

    @patch("rfc.providers.requests.get")
    def test_filters_free_suffix(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value=self._models_payload())
        )
        models = discover_free_models("https://openrouter.ai/api/v1", "sk-or-abc")
        assert models == [
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen3-32b:free",
        ]

    @patch("rfc.providers.requests.get")
    def test_queries_models_endpoint_with_auth(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"data": []})
        )
        discover_free_models("https://openrouter.ai/api/v1", "sk-or-abc")
        args, kwargs = mock_get.call_args
        assert args[0] == "https://openrouter.ai/api/v1/models"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-or-abc"

    @patch("rfc.providers.requests.get")
    def test_http_error_propagates(self, mock_get: MagicMock) -> None:
        response = MagicMock(status_code=500)
        response.raise_for_status.side_effect = req_lib.exceptions.HTTPError(
            response=response
        )
        mock_get.return_value = response
        with pytest.raises(req_lib.exceptions.HTTPError):
            discover_free_models("https://openrouter.ai/api/v1", "sk-or-abc")

    @patch("rfc.providers.requests.get")
    def test_malformed_entries_skipped(self, mock_get: MagicMock) -> None:
        payload = {"data": [{"no_id": True}, "just-a-string", {"id": "a/b:free"}]}
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value=payload)
        )
        models = discover_free_models("https://openrouter.ai/api/v1", "sk-or-abc")
        assert models == ["a/b:free"]

    @patch("rfc.providers.requests.get")
    def test_missing_data_key_returns_empty(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={})
        )
        assert discover_free_models("https://openrouter.ai/api/v1", "k") == []


class TestSelectModelsWithinBudget:
    def test_all_fit(self) -> None:
        # 2 models x 3 suites x 10 req = 60 <= 1000
        models = ["a:free", "b:free"]
        kept = select_models_within_budget(
            models, n_suites=3, max_requests_per_day=1000, requests_per_suite_estimate=10
        )
        assert kept == models

    def test_truncates_preserving_order(self) -> None:
        # each model costs 3 suites x 100 req = 300; budget 700 -> 2 models
        models = ["a:free", "b:free", "c:free"]
        kept = select_models_within_budget(
            models, n_suites=3, max_requests_per_day=700, requests_per_suite_estimate=100
        )
        assert kept == ["a:free", "b:free"]

    def test_zero_budget_keeps_nothing(self) -> None:
        kept = select_models_within_budget(
            ["a:free"], n_suites=1, max_requests_per_day=0, requests_per_suite_estimate=1
        )
        assert kept == []

    def test_empty_models(self) -> None:
        assert (
            select_models_within_budget(
                [], n_suites=5, max_requests_per_day=1000, requests_per_suite_estimate=10
            )
            == []
        )
