"""Tests for rfc.pre_run_modifier.ModelAwarePreRunModifier."""

import os
from unittest.mock import MagicMock, patch

import yaml

from rfc.pre_run_modifier import ModelAwarePreRunModifier


class TestPreRunModifierInit:
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_defaults(self, MockClient):
        mod = ModelAwarePreRunModifier()
        assert mod.ollama_endpoint == "http://localhost:11434"
        assert mod.config_path == "robot/ci/models.yaml"
        assert mod.default_model == "llama3"
        assert mod.available_models == []
        assert mod.model_config == {}

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

    @patch.dict(os.environ, {"OLLAMA_ENDPOINT": "http://env:11434", "DEFAULT_MODEL": "phi3"})
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

        mod = ModelAwarePreRunModifier(config_path=str(config_file))
        mod._load_model_config()

        assert "llama3" in mod.model_config
        assert mod.model_config["llama3"]["parameters"] == "8B"

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_load_missing_config(self, MockClient):
        mod = ModelAwarePreRunModifier(config_path="/nonexistent/models.yaml")
        mod._load_model_config()
        assert mod.model_config == {}

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_load_invalid_yaml(self, MockClient, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(": invalid: yaml: [")

        mod = ModelAwarePreRunModifier(config_path=str(config_file))
        mod._load_model_config()  # should not raise


class TestQueryAvailableModels:
    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_successful_query(self, MockClient):
        mock_client = MagicMock()
        mock_client.list_models.return_value = ["llama3", "mistral", "phi3"]
        MockClient.return_value = mock_client

        mod = ModelAwarePreRunModifier()
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
        mod = ModelAwarePreRunModifier()
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
        mod = ModelAwarePreRunModifier()
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
        mod = ModelAwarePreRunModifier()
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
        mod = ModelAwarePreRunModifier()
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
                "release_date": "2024-04-01",
                "parameters": "8B",
                "organization": "Meta",
            }
        }

        suite = MagicMock()
        suite.metadata = {}

        mod._add_metadata(suite)
        assert suite.metadata["Model_Name"] == "LLaMA 3"
        assert suite.metadata["Model_Parameters"] == "8B"

    @patch("rfc.pre_run_modifier.OllamaClient")
    def test_skips_empty_metadata(self, MockClient):
        mod = ModelAwarePreRunModifier()
        mod.ci_metadata = {"Branch": "main", "Tag": ""}
        mod.available_models = []

        suite = MagicMock()
        suite.metadata = {}

        mod._add_metadata(suite)
        assert suite.metadata["Branch"] == "main"
        assert "Tag" not in suite.metadata
