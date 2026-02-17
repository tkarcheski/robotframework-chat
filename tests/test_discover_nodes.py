"""Tests for scripts/discover_nodes.py — named-node discovery."""

from unittest.mock import patch

import yaml

from scripts.discover_nodes import (
    _load_node_list,
    _print_summary,
    _probe_node,
    _write_inventory,
    discover_all_nodes,
)


class TestLoadNodeList:
    @patch.dict("os.environ", {"OLLAMA_NODES_LIST": "host1,host2:9999"})
    def test_env_var_parsing(self):
        nodes = _load_node_list()
        assert len(nodes) == 2
        assert nodes[0] == {"hostname": "host1", "port": 11434}
        assert nodes[1] == {"hostname": "host2", "port": 9999}

    @patch.dict("os.environ", {"OLLAMA_NODES_LIST": ""})
    def test_config_file(self, tmp_path):
        config = {
            "nodes": [
                {"hostname": "mini1", "port": 11434},
                {"hostname": "ai1"},
            ]
        }
        config_file = tmp_path / "test_suites.yaml"
        config_file.write_text(yaml.dump(config))

        with patch("scripts.discover_nodes.CONFIG_PATH", config_file):
            nodes = _load_node_list()

        assert len(nodes) == 2
        assert nodes[0]["hostname"] == "mini1"
        assert nodes[1]["port"] == 11434  # default

    @patch.dict("os.environ", {"OLLAMA_NODES_LIST": ""})
    def test_no_config_returns_empty(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        with patch("scripts.discover_nodes.CONFIG_PATH", missing):
            nodes = _load_node_list()
        assert nodes == []

    @patch.dict("os.environ", {"OLLAMA_NODES_LIST": ",,,"})
    def test_empty_entries_skipped(self):
        nodes = _load_node_list()
        assert nodes == []


class TestProbeNode:
    @patch("scripts.discover_nodes._query_models", return_value=["llama3", "phi3"])
    @patch("scripts.discover_nodes._probe_port", return_value=True)
    def test_online_node(self, mock_probe, mock_models):
        result = _probe_node("mini1", 11434)
        assert result["online"] is True
        assert result["hostname"] == "mini1"
        assert result["endpoint"] == "http://mini1:11434"
        assert result["models"] == ["llama3", "phi3"]

    @patch("scripts.discover_nodes._probe_port", return_value=False)
    def test_offline_node(self, mock_probe):
        result = _probe_node("mini1", 11434)
        assert result["online"] is False
        assert result["models"] == []


class TestDiscoverAllNodes:
    @patch("scripts.discover_nodes._load_node_list", return_value=[])
    def test_no_nodes(self, mock_load):
        result = discover_all_nodes()
        assert result["nodes"] == []
        assert "last_updated" in result

    @patch("scripts.discover_nodes._probe_node")
    @patch(
        "scripts.discover_nodes._load_node_list",
        return_value=[
            {"hostname": "host1", "port": 11434},
            {"hostname": "host2", "port": 11434},
        ],
    )
    def test_multiple_nodes(self, mock_load, mock_probe):
        mock_probe.side_effect = lambda h, p: {
            "hostname": h,
            "endpoint": f"http://{h}:{p}",
            "online": h == "host1",
            "models": ["llama3"] if h == "host1" else [],
        }
        result = discover_all_nodes()
        assert len(result["nodes"]) == 2
        # sorted by hostname
        assert result["nodes"][0]["hostname"] == "host1"
        assert result["nodes"][1]["hostname"] == "host2"


class TestWriteInventory:
    def test_writes_yaml_file(self, tmp_path):
        inventory = {
            "last_updated": "2024-01-01T00:00:00+00:00",
            "nodes": [{"hostname": "mini1", "online": True}],
        }
        out = tmp_path / "inventory.yaml"
        _write_inventory(inventory, out)

        assert out.exists()
        content = out.read_text()
        assert "Auto-generated" in content
        loaded = yaml.safe_load(
            content.split("\n\n", 1)[1]  # skip header comments
        )
        assert loaded["nodes"][0]["hostname"] == "mini1"

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "sub" / "dir" / "inventory.yaml"
        _write_inventory({"last_updated": "now", "nodes": []}, out)
        assert out.exists()


class TestPrintSummary:
    def test_summary_output(self, capsys):
        inventory = {
            "last_updated": "2024-01-01T00:00:00",
            "nodes": [
                {
                    "hostname": "host1",
                    "endpoint": "http://host1:11434",
                    "online": True,
                    "models": ["llama3"],
                },
                {
                    "hostname": "host2",
                    "endpoint": "http://host2:11434",
                    "online": False,
                    "models": [],
                },
            ],
        }
        _print_summary(inventory)
        output = capsys.readouterr().out
        assert "Online:      1" in output
        assert "Offline:     1" in output
        assert "host1" in output
        assert "host2" in output

    def test_empty_summary(self, capsys):
        _print_summary({"last_updated": "now", "nodes": []})
        output = capsys.readouterr().out
        assert "Total nodes: 0" in output
