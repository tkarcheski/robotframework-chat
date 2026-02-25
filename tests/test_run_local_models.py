"""Tests for scripts/run_local_models.py — local model runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from scripts.run_local_models import (
    _build_robot_command,
    _sanitize_name,
    discover_local_models,
    load_local_config,
    run_model_suites,
)


class TestLoadLocalConfig:
    def test_loads_yaml(self, tmp_path: Path) -> None:
        cfg = {
            "discovery": {"connect_timeout": 3},
            "test_suites": [{"name": "math", "path": "robot/math/tests/"}],
            "execution": {"output_dir": "results/local/{node}/{model}"},
        }
        p = tmp_path / "local_models.yaml"
        p.write_text(yaml.dump(cfg))

        result = load_local_config(p)
        assert result["discovery"]["connect_timeout"] == 3
        assert len(result["test_suites"]) == 1

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_local_config(tmp_path / "nonexistent.yaml")


class TestSanitizeName:
    def test_basic(self) -> None:
        assert _sanitize_name("llama3:latest") == "llama3_latest"

    def test_slashes(self) -> None:
        assert (
            _sanitize_name("qwen3-coder:30b-a3b-q4_K_M") == "qwen3-coder_30b-a3b-q4_K_M"
        )

    def test_preserves_alphanumeric_dash_underscore(self) -> None:
        assert _sanitize_name("my-model_v2") == "my-model_v2"


class TestDiscoverLocalModels:
    @patch("scripts.run_local_models._query_models", return_value=["llama3", "mistral"])
    @patch("scripts.run_local_models._probe_port", return_value=True)
    def test_discovers_from_node_list(
        self, mock_probe: MagicMock, mock_models: MagicMock
    ) -> None:
        nodes = [
            {"hostname": "host1", "port": 11434},
        ]
        result = discover_local_models(nodes)
        assert len(result) == 1
        assert result[0]["endpoint"] == "http://host1:11434"
        assert result[0]["models"] == ["llama3", "mistral"]

    @patch("scripts.run_local_models._probe_port", return_value=False)
    def test_skips_offline_nodes(self, mock_probe: MagicMock) -> None:
        nodes = [{"hostname": "offline", "port": 11434}]
        result = discover_local_models(nodes)
        assert result == []

    def test_empty_nodes(self) -> None:
        result = discover_local_models([])
        assert result == []

    @patch("scripts.run_local_models._query_models", return_value=[])
    @patch("scripts.run_local_models._probe_port", return_value=True)
    def test_online_but_no_models(
        self, mock_probe: MagicMock, mock_models: MagicMock
    ) -> None:
        nodes = [{"hostname": "empty", "port": 11434}]
        result = discover_local_models(nodes)
        # Node is online but has no models — still included so user sees it
        assert len(result) == 1
        assert result[0]["models"] == []


class TestBuildRobotCommand:
    def test_basic_command(self) -> None:
        config = {
            "execution": {
                "output_dir": "results/local/{node}/{model}",
                "extra_args": [],
                "listeners": ["rfc.db_listener.DbListener"],
            }
        }
        suite = {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300}
        cmd = _build_robot_command(
            config=config,
            suite=suite,
            endpoint="http://host1:11434",
            model="llama3",
            node_name="host1",
        )
        assert cmd[0] == "uv"
        assert cmd[1] == "run"
        assert cmd[2] == "robot"
        assert "--listener" in cmd
        assert "rfc.db_listener.DbListener" in cmd
        assert any("OLLAMA_ENDPOINT:http://host1:11434" in a for a in cmd)
        assert any("DEFAULT_MODEL:llama3" in a for a in cmd)
        assert "robot/math/tests/" in cmd

    def test_output_dir_interpolation(self) -> None:
        config = {
            "execution": {
                "output_dir": "results/local/{node}/{model}",
                "extra_args": [],
                "listeners": [],
            }
        }
        suite = {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300}
        cmd = _build_robot_command(
            config=config,
            suite=suite,
            endpoint="http://host1:11434",
            model="qwen3-coder:30b",
            node_name="host1",
        )
        # Check -d flag value
        d_idx = cmd.index("-d")
        assert cmd[d_idx + 1] == "results/local/host1/qwen3-coder_30b"

    def test_extra_args_included(self) -> None:
        config = {
            "execution": {
                "output_dir": "results/{node}/{model}",
                "extra_args": ["--loglevel", "DEBUG"],
                "listeners": [],
            }
        }
        suite = {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300}
        cmd = _build_robot_command(
            config=config,
            suite=suite,
            endpoint="http://h:11434",
            model="m",
            node_name="h",
        )
        assert "--loglevel" in cmd
        assert "DEBUG" in cmd


class TestRunModelSuites:
    @patch("scripts.run_local_models.subprocess.run")
    def test_runs_all_suites_for_all_models(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        config = {
            "test_suites": [
                {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300},
            ],
            "execution": {
                "output_dir": "results/local/{node}/{model}",
                "extra_args": [],
                "listeners": [],
                "continue_on_failure": True,
                "parallel": 1,
            },
        }
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["llama3", "mistral"],
            },
        ]
        results = run_model_suites(config, nodes_with_models)
        assert len(results) == 2  # 1 suite x 2 models
        assert mock_run.call_count == 2

    @patch("scripts.run_local_models.subprocess.run")
    def test_continues_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=1),  # first fails
            MagicMock(returncode=0),  # second passes
        ]
        config = {
            "test_suites": [
                {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300},
            ],
            "execution": {
                "output_dir": "results/local/{node}/{model}",
                "extra_args": [],
                "listeners": [],
                "continue_on_failure": True,
                "parallel": 1,
            },
        }
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["llama3", "mistral"],
            },
        ]
        results = run_model_suites(config, nodes_with_models)
        assert len(results) == 2
        assert results[0].returncode == 1
        assert results[1].returncode == 0

    @patch("scripts.run_local_models.subprocess.run")
    def test_result_fields(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        config = {
            "test_suites": [
                {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300},
            ],
            "execution": {
                "output_dir": "results/local/{node}/{model}",
                "extra_args": [],
                "listeners": [],
                "continue_on_failure": True,
                "parallel": 1,
            },
        }
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["llama3"],
            },
        ]
        results = run_model_suites(config, nodes_with_models)
        r = results[0]
        assert r.node == "host1"
        assert r.model == "llama3"
        assert r.suite == "math"
        assert r.returncode == 0

    @patch("scripts.run_local_models.subprocess.run")
    def test_no_models_no_runs(self, mock_run: MagicMock) -> None:
        config = {
            "test_suites": [
                {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300},
            ],
            "execution": {
                "output_dir": "results/local/{node}/{model}",
                "extra_args": [],
                "listeners": [],
                "continue_on_failure": True,
                "parallel": 1,
            },
        }
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": [],
            },
        ]
        results = run_model_suites(config, nodes_with_models)
        assert results == []
        mock_run.assert_not_called()
