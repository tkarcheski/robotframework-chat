"""Tests for rfc.pre_run_modifier.ModelAwarePreRunModifier."""

import os
from unittest.mock import MagicMock, patch

import yaml

from rfc.pre_run_modifier import ModelAwarePreRunModifier, main


class TestPreRunModifierInit:
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_missing_model_raises(self, MockClient):
        """No silent fallback: instantiation must fail when DEFAULT_MODEL is unset.

        A hardcoded default (e.g. ``phi4:14b``) would silently mislabel runs.
        """
        import pytest

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OLLAMA_ENDPOINT", None)
            os.environ.pop("DEFAULT_MODEL", None)
            with pytest.raises(ValueError, match="No model configured"):
                ModelAwarePreRunModifier()

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_custom_args(self, MockClient):
        mod = ModelAwarePreRunModifier(
            ollama_endpoint="http://custom:11434",
            config_path="/custom/models.yaml",
            default_model="mistral",
        )
        assert mod.ollama_endpoint == "http://custom:11434"
        assert mod.config_path == "/custom/models.yaml"
        assert mod.default_model == "mistral"

    @patch.dict(
        os.environ, {"OLLAMA_ENDPOINT": "http://env:11434", "DEFAULT_MODEL": "phi3"}
    )
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_env_vars(self, MockClient):
        mod = ModelAwarePreRunModifier()
        assert mod.ollama_endpoint == "http://env:11434"
        assert mod.default_model == "phi3"


class TestLoadModelConfig:
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_load_existing_config(self, MockClient, tmp_path):
        config_file = tmp_path / "models.yaml"
        config_file.write_text(yaml.dump({"models": {"llama3": {"parameters": "8B"}}}))

        mod = ModelAwarePreRunModifier(
            config_path=str(config_file), default_model="test-model"
        )
        mod._load_model_config()

        assert "llama3" in mod.model_config
        assert mod.model_config["llama3"]["parameters"] == "8B"

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_load_missing_config(self, MockClient):
        mod = ModelAwarePreRunModifier(
            config_path="/nonexistent/models.yaml", default_model="test-model"
        )
        mod._load_model_config()
        assert mod.model_config == {}

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_load_invalid_yaml(self, MockClient, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(": invalid: yaml: [")

        mod = ModelAwarePreRunModifier(
            config_path=str(config_file), default_model="test-model"
        )
        mod._load_model_config()  # should not raise


class TestQueryAvailableModels:
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_successful_query(self, MockClient):
        mock_client = MagicMock()
        mock_client.list_models.return_value = ["llama3", "mistral", "phi3"]
        MockClient.return_value = mock_client

        mod = ModelAwarePreRunModifier(default_model="llama3")
        mod._query_available_models()

        assert mod.available_models == ["llama3", "mistral", "phi3"]

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_query_fails_uses_default(self, MockClient):
        mock_client = MagicMock()
        mock_client.list_models.side_effect = Exception("connection refused")
        MockClient.return_value = mock_client

        mod = ModelAwarePreRunModifier(default_model="phi3")
        mod._query_available_models()

        assert mod.available_models == ["phi3"]


class TestFilterTestsByModels:
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_no_model_tags_keeps_all(self, MockClient):
        mod = ModelAwarePreRunModifier(default_model="llama3")
        mod.available_models = ["llama3"]

        suite = MagicMock()
        suite.name = "math"
        suite.metadata = {}
        test1 = MagicMock()
        test1.tags = []
        test1.name = "Test 1"
        suite.tests = [test1]

        mod._filter_tests_by_models(suite)
        assert len(suite.tests) == 1

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_removes_tests_requiring_unavailable_model(self, MockClient):
        mod = ModelAwarePreRunModifier(default_model="llama3")
        mod.available_models = ["llama3"]

        suite = MagicMock()
        suite.name = "math"
        suite.metadata = {}
        test1 = MagicMock()
        test1.tags = ["model:codellama"]
        test1.name = "Code Test"
        test2 = MagicMock()
        test2.tags = ["model:llama3"]
        test2.name = "Math Test"
        suite.tests = [test1, test2]

        mod._filter_tests_by_models(suite)
        # test1 requires codellama which is not available, so it should be removed
        assert test1 not in suite.tests
        assert test2 in suite.tests

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_keeps_tests_with_available_model(self, MockClient):
        mod = ModelAwarePreRunModifier(default_model="llama3")
        mod.available_models = ["llama3", "codellama"]

        suite = MagicMock()
        suite.name = "math"
        suite.metadata = {}
        test1 = MagicMock()
        test1.tags = ["model:codellama"]
        test1.name = "Code Test"
        suite.tests = [test1]

        mod._filter_tests_by_models(suite)
        assert test1 in suite.tests


class TestAddMetadata:
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_adds_ci_metadata(self, MockClient):
        mod = ModelAwarePreRunModifier(default_model="llama3")
        mod.ci_metadata = {"Branch": "main", "Commit_SHA": "abc123"}
        mod.available_models = ["llama3"]

        suite = MagicMock()
        suite.metadata = {}

        mod._add_metadata(suite)
        assert suite.metadata["Branch"] == "main"
        assert suite.metadata["Commit_SHA"] == "abc123"
        assert "All_Available_Models" in suite.metadata

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_adds_model_info(self, MockClient):
        mod = ModelAwarePreRunModifier(default_model="llama3")
        mod.ci_metadata = {}
        mod.available_models = ["llama3"]
        mod.model_config = {
            "llama3": {
                "full_name": "LLaMA 3",
                "organization": "Meta",
            }
        }

        suite = MagicMock()
        suite.metadata = {}

        mod._add_metadata(suite)
        assert suite.metadata["Model_Name"] == "LLaMA 3"
        assert suite.metadata["Model_Organization"] == "Meta"

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_skips_empty_metadata(self, MockClient):
        mod = ModelAwarePreRunModifier(default_model="llama3")
        mod.ci_metadata = {"Branch": "main", "Tag": ""}
        mod.available_models = []

        suite = MagicMock()
        suite.metadata = {}

        mod._add_metadata(suite)
        assert suite.metadata["Branch"] == "main"
        assert "Tag" not in suite.metadata


# ── start_suite (full integration of modifier) ──────────────────────


class TestPreRunModifierStartSuite:
    @patch("rfc.pre_run_modifier.OllamaClient")
    @patch("rfc.pre_run_modifier.collect_ci_metadata", return_value={"Branch": "main"})
    def test_start_suite_runs_full_pipeline(self, _mock_ci, MockClient, tmp_path):
        """start_suite should gather CI metadata, load config, query models, filter, and add metadata."""
        config_file = tmp_path / "models.yaml"
        config_file.write_text(yaml.dump({"models": {"llama3": {"parameters": "8B"}}}))

        mock_client = MagicMock()
        mock_client.list_models.return_value = ["llama3", "phi4:14b"]
        MockClient.return_value = mock_client

        mod = ModelAwarePreRunModifier(
            config_path=str(config_file), default_model="llama3"
        )

        suite = MagicMock()
        suite.name = "Math"
        suite.metadata = {}
        test1 = MagicMock()
        test1.tags = []
        test1.name = "Test 1"
        suite.tests = [test1]

        mod.start_suite(suite)

        assert "Branch" in suite.metadata
        assert "All_Available_Models" in suite.metadata
        assert "Selected_Model" in suite.metadata
        assert mod.available_models == ["llama3", "phi4:14b"]


# ── main() ───────────────────────────────────────────────────────────


class TestPreRunModifierMain:
    @patch.dict(os.environ, {"DEFAULT_MODEL": "llama3"})
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_main_with_models(self, MockClient, capsys):
        mock_client = MagicMock()
        mock_client.list_models.return_value = ["llama3"]
        MockClient.return_value = mock_client

        result = main()
        captured = capsys.readouterr()
        assert "Available models" in captured.out
        assert result == 0

    @patch.dict(os.environ, {"DEFAULT_MODEL": "llama3"})
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_main_no_models(self, MockClient, capsys):
        mock_client = MagicMock()
        mock_client.list_models.side_effect = Exception("offline")
        MockClient.return_value = mock_client

        main()
        captured = capsys.readouterr()
        assert "Available models" in captured.out
