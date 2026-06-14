"""Tests for rfc.providers — external OpenAI-compatible providers (issue #507)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from rfc.providers import (
    ProviderConfig,
    discover_free_models,
    load_providers,
    resolve_api_key,
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


class TestMaxContextTokens:
    def test_default_is_unlimited(self) -> None:
        providers = load_providers(
            {
                "providers": [
                    {
                        "name": "groq",
                        "base_url": "https://api.groq.com/openai/v1",
                        "api_key_env": "GROQ_API_KEY",
                    }
                ]
            }
        )
        assert providers[0].max_context_tokens == 0

    def test_parses_explicit_cap(self) -> None:
        providers = load_providers(
            {
                "providers": [
                    {
                        "name": "cerebras",
                        "base_url": "https://api.cerebras.ai/v1",
                        "api_key_env": "CEREBRAS_API_KEY",
                        "max_context_tokens": 8192,
                    }
                ]
            }
        )
        assert providers[0].max_context_tokens == 8192


class TestConfiguredFreeTierProviders:
    """The committed config must declare the free-tier providers (#509)."""

    @staticmethod
    def _real_providers() -> dict[str, "ProviderConfig"]:
        import yaml

        root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load((root / "config" / "local_models.yaml").read_text())
        return {p.name: p for p in load_providers(config)}

    def test_groq_cerebras_google_declared(self) -> None:
        providers = self._real_providers()
        assert providers["groq"].api_key_env == "GROQ_API_KEY"
        assert providers["cerebras"].api_key_env == "CEREBRAS_API_KEY"
        assert providers["google-ai-studio"].api_key_env == "GOOGLE_AI_STUDIO_API_KEY"
        # static model lists, no ":free" discovery convention on these APIs
        for name in ("groq", "cerebras", "google-ai-studio"):
            assert providers[name].models, f"{name} needs a static model list"
            assert not providers[name].discover_free_pool

    def test_cerebras_context_cap_declared(self) -> None:
        assert self._real_providers()["cerebras"].max_context_tokens == 8192

    def test_env_example_documents_all_keys(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env_example = (root / ".env.example").read_text()
        for key in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "GOOGLE_AI_STUDIO_API_KEY"):
            assert key in env_example


class TestCerebrasReviewFindings521:
    """Cerebras config must be runnable: a valid model id and a budget big
    enough to schedule at least one model across the suite set (#521)."""

    @staticmethod
    def _config() -> dict:
        import yaml

        root = Path(__file__).resolve().parents[1]
        return yaml.safe_load((root / "config" / "local_models.yaml").read_text())

    def _cerebras(self):
        return next(p for p in load_providers(self._config()) if p.name == "cerebras")

    # Cerebras deprecation dates (inference-docs.cerebras.ai/support/deprecation):
    # llama-3.3-70b 2026-02-16, llama3.1-8b 2026-05-27.
    _DEPRECATED_CEREBRAS = ("llama-3.3-70b", "llama3.1-8b", "llama3.1-70b")

    def test_no_deprecated_cerebras_models(self) -> None:
        cerebras = self._cerebras()
        for retired in self._DEPRECATED_CEREBRAS:
            assert retired not in cerebras.models, f"{retired} is retired"
        # at least one current production model (gpt-oss-120b)
        assert "gpt-oss-120b" in cerebras.models


class TestProviderModelsCurrent521R3:
    """Configured provider models must be currently available (#521)."""

    @staticmethod
    def _config() -> dict:
        import yaml

        root = Path(__file__).resolve().parents[1]
        return yaml.safe_load((root / "config" / "local_models.yaml").read_text())

    def _provider(self, name: str):
        return next(p for p in load_providers(self._config()) if p.name == name)

    def test_google_model_is_not_shut_down_gemini_2_0(self) -> None:
        # gemini-2.0-flash shut down 2026-06-01; use a current Flash model.
        google = self._provider("google-ai-studio")
        assert "gemini-2.0-flash" not in google.models
        assert any("flash" in m for m in google.models)

    def test_benchmark_suite_declares_context_requirement(self) -> None:
        # The benchmark suite drives num_ctx up to 131584; without
        # min_context_tokens the Cerebras 8K cap silently never skips it (#521).
        cfg = self._config()
        bench = next(s for s in cfg["test_suites"] if s["name"] == "benchmark")
        assert bench.get("min_context_tokens", 0) > 8192


class TestProviderQuotas521R4:
    """Free-tier quotas must match the chosen model so the sweep doesn't
    429: Gemini 2.5 Flash is 10 RPM/250 RPD (too low to sweep) — use
    Flash-Lite (15 RPM/1000 RPD); Groq's 8B context is 131072, so the
    benchmark (131584 num_ctx) is skipped via the context cap (#521)."""

    @staticmethod
    def _config() -> dict:
        import yaml

        root = Path(__file__).resolve().parents[1]
        return yaml.safe_load((root / "config" / "local_models.yaml").read_text())

    def _provider(self, name: str):
        return next(p for p in load_providers(self._config()) if p.name == name)

    def test_groq_declares_context_cap_to_skip_benchmark(self) -> None:
        groq = self._provider("groq")
        # llama-3.1-8b-instant context window is 131072; the benchmark needs
        # 131584, so the cap must be set to skip it (not unlimited).
        assert 0 < groq.max_context_tokens <= 131072


class TestAllowLocalOnly:
    def test_default_false(self) -> None:
        providers = load_providers(
            {
                "providers": [
                    {
                        "name": "groq",
                        "base_url": "https://api.groq.com/openai/v1",
                        "api_key_env": "GROQ_API_KEY",
                    }
                ]
            }
        )
        assert providers[0].allow_local_only is False

    def test_parses_explicit_allowlist_flag(self) -> None:
        providers = load_providers(
            {
                "providers": [
                    {
                        "name": "paid-zdr",
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "ZDR_API_KEY",
                        "allow_local_only": True,
                    }
                ]
            }
        )
        assert providers[0].allow_local_only is True


class TestStrictBoolParsing:
    """allow_local_only is a security boundary; bool('false') is True, so a
    quoted/templated false-looking value must fail closed (#525)."""

    def _provider(self, value):
        return load_providers(
            {
                "providers": [
                    {
                        "name": "p",
                        "base_url": "https://x/v1",
                        "api_key_env": "K",
                        "allow_local_only": value,
                    }
                ]
            }
        )[0]

    @pytest.mark.parametrize("value", ["false", "False", "no", "0", "off", ""])
    def test_falsey_strings_fail_closed(self, value: str) -> None:
        assert self._provider(value).allow_local_only is False

    @pytest.mark.parametrize("value", ["true", "True", "yes", "1", "on"])
    def test_truthy_strings_enable(self, value: str) -> None:
        assert self._provider(value).allow_local_only is True

    def test_native_booleans_preserved(self) -> None:
        assert self._provider(True).allow_local_only is True
        assert self._provider(False).allow_local_only is False

    def test_unknown_string_fails_closed(self) -> None:
        assert self._provider("maybe").allow_local_only is False
