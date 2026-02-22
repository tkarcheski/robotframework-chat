"""Tests for scripts/discover_ollama.py — network discovery helpers."""

from unittest.mock import MagicMock, patch

from scripts.discover_ollama import (
    _from_env_nodes,
    _from_subnet,
    _normalise_endpoint,
    _probe_port,
    _query_models,
    discover_nodes,
)


class TestNormaliseEndpoint:
    def test_default_port(self):
        assert _normalise_endpoint("myhost") == "http://myhost:11434"

    def test_custom_port(self):
        assert _normalise_endpoint("myhost", 9999) == "http://myhost:9999"


class TestProbePort:
    @patch("scripts.discover_ollama.socket.create_connection")
    def test_port_open(self, mock_conn):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        assert _probe_port("localhost", 11434) is True

    @patch("scripts.discover_ollama.socket.create_connection")
    def test_port_closed(self, mock_conn):
        mock_conn.side_effect = OSError("Connection refused")
        assert _probe_port("localhost", 11434) is False

    @patch("scripts.discover_ollama.socket.create_connection")
    def test_port_timeout(self, mock_conn):
        mock_conn.side_effect = TimeoutError("timed out")
        assert _probe_port("localhost", 11434) is False


class TestQueryModels:
    @patch("scripts.discover_ollama.requests.get")
    def test_successful_query(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [{"name": "llama3"}, {"name": "mistral"}]
        }
        mock_get.return_value = mock_resp
        assert _query_models("http://localhost:11434") == ["llama3", "mistral"]

    @patch("scripts.discover_ollama.requests.get")
    def test_empty_models(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_get.return_value = mock_resp
        assert _query_models("http://localhost:11434") == []

    @patch("scripts.discover_ollama.requests.get")
    def test_connection_error(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        assert _query_models("http://localhost:11434") == []


class TestFromEnvNodes:
    @patch.dict("os.environ", {"OLLAMA_NODES": ""})
    def test_empty_env(self):
        assert _from_env_nodes() == []

    @patch.dict("os.environ", {"OLLAMA_NODES": "host1:11434,host2:11435"})
    def test_host_port_pairs(self):
        result = _from_env_nodes()
        assert result == [
            "http://host1:11434",
            "http://host2:11435",
        ]

    @patch.dict("os.environ", {"OLLAMA_NODES": "host1,host2"})
    def test_hosts_without_ports(self):
        result = _from_env_nodes()
        assert result == [
            "http://host1:11434",
            "http://host2:11434",
        ]

    @patch.dict("os.environ", {"OLLAMA_NODES": "http://custom:8080"})
    def test_full_url(self):
        result = _from_env_nodes()
        assert result == ["http://custom:8080"]

    @patch.dict("os.environ", {}, clear=False)
    def test_missing_env(self):
        import os

        os.environ.pop("OLLAMA_NODES", None)
        assert _from_env_nodes() == []


class TestFromSubnet:
    @patch.dict("os.environ", {"OLLAMA_SUBNET": ""})
    def test_empty_subnet(self):
        assert _from_subnet() == []

    @patch.dict("os.environ", {"OLLAMA_SUBNET": "not_a_subnet"})
    def test_invalid_subnet(self):
        assert _from_subnet() == []

    @patch("scripts.discover_ollama._probe_port")
    @patch.dict("os.environ", {"OLLAMA_SUBNET": "192.168.1.0/30"})
    def test_small_subnet(self, mock_probe):
        # /30 has 2 usable hosts: .1 and .2
        mock_probe.side_effect = lambda h, p: h == "192.168.1.1"
        result = _from_subnet()
        assert "http://192.168.1.1:11434" in result
        assert "http://192.168.1.2:11434" not in result


class TestDiscoverNodes:
    @patch("scripts.discover_ollama._from_env_nodes", return_value=[])
    @patch("scripts.discover_ollama._from_subnet", return_value=[])
    @patch("scripts.discover_ollama._query_models")
    def test_falls_back_to_localhost(self, mock_query, mock_subnet, mock_env):
        mock_query.return_value = ["llama3"]
        result = discover_nodes()
        assert len(result) == 1
        assert result[0]["endpoint"] == "http://localhost:11434"
        assert result[0]["models"] == ["llama3"]

    @patch(
        "scripts.discover_ollama._from_env_nodes",
        return_value=["http://host1:11434", "http://host2:11434"],
    )
    @patch("scripts.discover_ollama._query_models")
    def test_uses_env_nodes(self, mock_query, mock_env):
        mock_query.side_effect = lambda ep: ["llama3"] if "host1" in ep else []
        result = discover_nodes()
        assert len(result) == 1
        assert result[0]["endpoint"] == "http://host1:11434"

    @patch("scripts.discover_ollama._from_env_nodes", return_value=[])
    @patch("scripts.discover_ollama._from_subnet", return_value=[])
    @patch("scripts.discover_ollama._query_models", return_value=[])
    def test_no_models_found(self, mock_query, mock_subnet, mock_env):
        result = discover_nodes()
        assert result == []
