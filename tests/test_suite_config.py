"""Tests for rfc.suite_config."""

import os
from unittest.mock import patch

from rfc.suite_config import (
    _apply_env_overrides,
    defaults,
    test_suites,
    run_all_entry,
    iq_levels,
    container_profiles,
    nodes,
    master_models,
    ci_config,
    suite_dropdown_options,
    iq_dropdown_options,
    profile_dropdown_options,
    node_dropdown_options,
    default_model,
    default_iq_levels,
    default_profile,
    load_config,
)


class TestConvenienceAccessors:
    def setup_method(self):
        load_config.cache_clear()

    def teardown_method(self):
        load_config.cache_clear()

    def test_defaults_returns_dict(self, mock_suite_config):
        result = defaults()
        assert isinstance(result, dict)
        assert "model" in result

    def test_test_suites_returns_dict(self, mock_suite_config):
        result = test_suites()
        assert isinstance(result, dict)
        assert "math" in result

    def test_iq_levels_returns_list(self, mock_suite_config):
        result = iq_levels()
        assert isinstance(result, list)
        assert "100" in result

    def test_container_profiles_returns_dict(self, mock_suite_config):
        result = container_profiles()
        assert isinstance(result, dict)
        assert "STANDARD" in result

    def test_nodes_returns_list(self, mock_suite_config):
        result = nodes()
        assert isinstance(result, list)
        assert result[0]["hostname"] == "localhost"

    def test_master_models_returns_list(self, mock_suite_config):
        result = master_models()
        assert isinstance(result, list)
        assert "llama3" in result

    def test_ci_config_returns_dict(self, mock_suite_config):
        result = ci_config()
        assert isinstance(result, dict)

    def test_run_all_entry_returns_dict(self, mock_suite_config):
        result = run_all_entry()
        assert "label" in result
        assert "path" in result


class TestDropdownBuilders:
    def setup_method(self):
        load_config.cache_clear()

    def teardown_method(self):
        load_config.cache_clear()

    def test_suite_dropdown_has_run_all(self, mock_suite_config):
        options = suite_dropdown_options()
        assert options[0]["label"] == "Run All"

    def test_suite_dropdown_has_all_suites(self, mock_suite_config):
        options = suite_dropdown_options()
        # Run All + math = 2
        assert len(options) >= 2

    def test_iq_dropdown_format(self, mock_suite_config):
        options = iq_dropdown_options()
        assert options[0]["label"].startswith("IQ:")
        assert options[0]["value"] in ["100", "110", "120"]

    def test_profile_dropdown_format(self, mock_suite_config):
        options = profile_dropdown_options()
        assert len(options) >= 1
        assert options[0]["value"] == "STANDARD"

    def test_node_dropdown_format(self, mock_suite_config):
        options = node_dropdown_options()
        assert "localhost:11434" in options[0]["value"]

    def test_node_dropdown_fallback(self):
        load_config.cache_clear()
        with patch("rfc.suite_config.load_config") as mock_load:
            mock_load.return_value = {"nodes": []}
            load_config.cache_clear()
            options = node_dropdown_options()
            assert options[0]["value"] == "localhost:11434"
        load_config.cache_clear()


class TestDefaultHelpers:
    def setup_method(self):
        load_config.cache_clear()

    def teardown_method(self):
        load_config.cache_clear()

    def test_default_model(self, mock_suite_config):
        assert default_model() == "llama3"

    def test_default_iq_levels(self, mock_suite_config):
        result = default_iq_levels()
        assert isinstance(result, list)
        assert "100" in result

    def test_default_profile(self, mock_suite_config):
        assert default_profile() == "STANDARD"


class TestEnvVarOverrides:
    """Env vars from .env override YAML config values."""

    def test_default_model_overridden_by_env(self):
        cfg = {"defaults": {"model": "llama3"}}
        with patch.dict(os.environ, {"DEFAULT_MODEL": "mistral"}):
            result = _apply_env_overrides(cfg)
        assert result["defaults"]["model"] == "mistral"

    def test_ollama_endpoint_overridden_by_env(self):
        cfg = {"defaults": {"ollama_endpoint": "http://localhost:11434"}}
        with patch.dict(os.environ, {"OLLAMA_ENDPOINT": "http://gpu1:11434"}):
            result = _apply_env_overrides(cfg)
        assert result["defaults"]["ollama_endpoint"] == "http://gpu1:11434"

    def test_gitlab_api_url_overridden_by_env(self):
        cfg = {"monitoring": {"gitlab_api_url": ""}}
        with patch.dict(os.environ, {"GITLAB_API_URL": "https://gitlab.example.com"}):
            result = _apply_env_overrides(cfg)
        assert result["monitoring"]["gitlab_api_url"] == "https://gitlab.example.com"

    def test_empty_env_var_does_not_override(self):
        cfg = {"defaults": {"model": "llama3"}}
        with patch.dict(os.environ, {"DEFAULT_MODEL": ""}, clear=False):
            result = _apply_env_overrides(cfg)
        assert result["defaults"]["model"] == "llama3"

    def test_missing_section_created_by_override(self):
        cfg = {}
        with patch.dict(os.environ, {"DEFAULT_MODEL": "phi3"}):
            result = _apply_env_overrides(cfg)
        assert result["defaults"]["model"] == "phi3"
