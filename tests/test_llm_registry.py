"""Tests for dashboard.core.llm_registry."""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from dashboard.core.llm_registry import LLMRegistry


def _mock_client_factory(models_by_host=None):
    """Create a mock OllamaClient factory.

    ``models_by_host`` is a dict mapping ``host:port`` -> list of model dicts.
    """
    models_by_host = models_by_host or {}

    def factory(base_url=""):
        client = MagicMock()
        # Extract host:port from base_url
        host_port = base_url.replace("http://", "").replace("https://", "")
        models = models_by_host.get(host_port, [])
        client.list_models_detailed.return_value = models
        client.is_available.return_value = bool(models)
        return client

    return factory


class TestLLMRegistry:
    def test_init_empty_state(self):
        reg = LLMRegistry()
        assert reg._node_models == {}
        assert reg._last_update == 0

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_refresh_models_single_node(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        mock_client = MagicMock()
        mock_client.list_models_detailed.return_value = [
            {
                "name": "llama3",
                "size": 1000,
                "modified_at": "2024-01-01",
                "digest": "abc",
            },
        ]
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()

        assert "llama3" in reg.get_models()

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_refresh_models_multiple_nodes(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        calls = []

        def side_effect(base_url=""):
            client = MagicMock()
            if "host1" in base_url:
                client.list_models_detailed.return_value = [
                    {"name": "llama3", "size": 1000, "modified_at": "x", "digest": "a"},
                ]
            else:
                client.list_models_detailed.return_value = [
                    {"name": "mistral", "size": 500, "modified_at": "x", "digest": "b"},
                ]
            calls.append(base_url)
            return client

        mock_cls.side_effect = side_effect

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1,host2", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()

        models = reg.get_models()
        assert "llama3" in models
        assert "mistral" in models

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_refresh_models_node_offline(self, mock_cls, mock_nodes):
        reg = LLMRegistry()

        def side_effect(base_url=""):
            client = MagicMock()
            if "bad" in base_url:
                client.list_models_detailed.side_effect = Exception("offline")
            else:
                client.list_models_detailed.return_value = [
                    {"name": "llama3", "size": 1000, "modified_at": "x", "digest": "a"},
                ]
            return client

        mock_cls.side_effect = side_effect

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "good,bad", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()

        assert "llama3" in reg.get_models()

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_refresh_models_all_offline(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        mock_client = MagicMock()
        mock_client.list_models_detailed.side_effect = Exception("offline")
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "bad1,bad2", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()

        assert reg.get_models() == []

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_cache_ttl_prevents_refresh(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        mock_client = MagicMock()
        mock_client.list_models_detailed.return_value = []
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()
            initial_calls = mock_client.list_models_detailed.call_count
            # Second call within TTL should not refresh
            reg.get_models()
            assert mock_client.list_models_detailed.call_count == initial_calls

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_cache_ttl_expired_triggers_refresh(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        reg._cache_ttl = 0  # Expire immediately
        mock_client = MagicMock()
        mock_client.list_models_detailed.return_value = []
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()
            reg._last_update = 0  # Force expiry
            reg.get_models()
            assert mock_client.list_models_detailed.call_count >= 2

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_get_models_deduplicates(self, mock_cls, mock_nodes):
        reg = LLMRegistry()

        def side_effect(base_url=""):
            client = MagicMock()
            client.list_models_detailed.return_value = [
                {"name": "llama3", "size": 1000, "modified_at": "x", "digest": "a"},
            ]
            return client

        mock_cls.side_effect = side_effect

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1,host2", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()

        models = reg.get_models()
        assert models.count("llama3") == 1

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_get_models_sorted(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        mock_client = MagicMock()
        mock_client.list_models_detailed.return_value = [
            {"name": "zebra", "size": 100, "modified_at": "x", "digest": "a"},
            {"name": "alpha", "size": 100, "modified_at": "x", "digest": "b"},
        ]
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()

        assert reg.get_models() == ["alpha", "zebra"]

    @patch(
        "dashboard.core.llm_registry.master_models",
        return_value=["llama3", "missing_model"],
    )
    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_get_all_models_includes_unavailable_master(
        self, mock_cls, mock_nodes, mock_masters
    ):
        reg = LLMRegistry()
        mock_client = MagicMock()
        mock_client.list_models_detailed.return_value = [
            {"name": "llama3", "size": 1000, "modified_at": "x", "digest": "a"},
        ]
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            reg.refresh_models()

        options = reg.get_all_models()
        values = [o["value"] for o in options]
        assert "llama3" in values
        assert "missing_model" in values
        # missing_model should be disabled
        missing = [o for o in options if o["value"] == "missing_model"][0]
        assert missing.get("disabled") is True

    def test_models_on_node_invalid_type(self):
        reg = LLMRegistry()
        reg._last_update = time.time()  # Prevent refresh
        with pytest.raises(TypeError, match="host_port must be a str"):
            reg.models_on_node(123)

    def test_models_on_node_empty_string(self):
        reg = LLMRegistry()
        reg._last_update = time.time()
        with pytest.raises(ValueError, match="non-empty string"):
            reg.models_on_node("")

    def test_models_on_node_unknown(self):
        reg = LLMRegistry()
        reg._last_update = time.time()
        assert reg.models_on_node("unknown:11434") == []

    def test_get_model_info_invalid_type(self):
        reg = LLMRegistry()
        reg._last_update = time.time()
        with pytest.raises(TypeError, match="model_name must be a str"):
            reg.get_model_info(123)

    def test_get_model_info_empty_string(self):
        reg = LLMRegistry()
        reg._last_update = time.time()
        with pytest.raises(ValueError, match="non-empty string"):
            reg.get_model_info("")

    def test_get_model_info_nonexistent(self):
        reg = LLMRegistry()
        reg._last_update = time.time()
        assert reg.get_model_info("nonexistent") == {}

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_is_available_one_node_up(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            assert reg.is_available() is True

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    @patch("dashboard.core.llm_registry.OllamaClient")
    def test_is_available_all_down(self, mock_cls, mock_nodes):
        reg = LLMRegistry()
        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        mock_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "host1", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            assert reg.is_available() is False

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    def test_get_node_list_from_env(self, mock_nodes):
        reg = LLMRegistry()
        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "a,b,c", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            node_list = reg._get_node_list()
        assert len(node_list) == 3
        assert node_list[0]["hostname"] == "a"

    @patch("dashboard.core.llm_registry.nodes")
    def test_get_node_list_from_config(self, mock_nodes):
        mock_nodes.return_value = [{"hostname": "cfg-host", "port": 1234}]
        reg = LLMRegistry()
        with patch.dict(
            os.environ,
            {"OLLAMA_NODES_LIST": "", "OLLAMA_ENDPOINT": ""},
            clear=False,
        ):
            node_list = reg._get_node_list()
        assert node_list[0]["hostname"] == "cfg-host"

    @patch("dashboard.core.llm_registry.nodes", return_value=[])
    def test_get_node_list_fallback_to_endpoint(self, mock_nodes):
        reg = LLMRegistry()
        with patch.dict(
            os.environ,
            {
                "OLLAMA_NODES_LIST": "",
                "OLLAMA_ENDPOINT": "http://myhost:9999",
            },
            clear=False,
        ):
            node_list = reg._get_node_list()
        assert node_list[0]["hostname"] == "myhost"
        assert node_list[0]["port"] == 9999
