"""Tests for scripts/run_local_models.py — local model runner."""

from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from scripts.run_local_models import (
    RunResult,
    _build_robot_command,
    _sanitize_name,
    discover_local_models,
    load_local_config,
    run_iteration_loop,
    run_model_suites,
    verify_db_results,
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
    def test_passes_env_with_model_and_endpoint(self, mock_run: MagicMock) -> None:
        """subprocess.run receives env with DEFAULT_MODEL and OLLAMA_ENDPOINT."""
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
        run_model_suites(config, nodes_with_models)
        call_kwargs = mock_run.call_args
        env = call_kwargs.kwargs.get("env")
        assert env is not None, "subprocess.run must be called with env= keyword"
        assert env["DEFAULT_MODEL"] == "llama3"
        assert env["OLLAMA_ENDPOINT"] == "http://host1:11434"

    @patch("scripts.run_local_models.subprocess.run")
    def test_shuffles_model_order(self, mock_run: MagicMock) -> None:
        """Models are shuffled before execution (not always alphabetical)."""
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
        models = ["alpha", "bravo", "charlie", "delta"]
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": list(models),
            },
        ]
        # Patch random.shuffle to reverse the list (deterministic non-alphabetical order)
        with patch(
            "scripts.run_local_models.random.shuffle", side_effect=lambda x: x.reverse()
        ):
            results = run_model_suites(config, nodes_with_models)

        # Models should have been run in reversed order
        executed_models = [r.model for r in results]
        assert executed_models == ["delta", "charlie", "bravo", "alpha"]

    @patch("scripts.run_local_models.subprocess.run")
    def test_shuffle_does_not_mutate_input(self, mock_run: MagicMock) -> None:
        """Shuffling models must not mutate the original nodes_with_models."""
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
                "models": ["alpha", "bravo", "charlie"],
            },
        ]
        original = copy.deepcopy(nodes_with_models)
        run_model_suites(config, nodes_with_models)
        assert nodes_with_models == original, (
            "Input nodes_with_models must not be mutated"
        )

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


# ---------------------------------------------------------------------------
# Helpers for iteration tests
# ---------------------------------------------------------------------------

_ITER_CONFIG: dict = {
    "discovery": {"connect_timeout": 2, "max_workers": 64},
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

_ITER_NODES = [{"hostname": "host1", "port": 11434}]

_ITER_DISCOVERED = [
    {
        "endpoint": "http://host1:11434",
        "hostname": "host1",
        "models": ["llama3"],
    },
]


def _make_pass_result() -> list:
    return [MagicMock(returncode=0, node="host1", model="llama3", suite="math")]


def _make_fail_result() -> list:
    return [MagicMock(returncode=1, node="host1", model="llama3", suite="math")]


class TestRunIterationLoop:
    """Tests for the run_iteration_loop() outer loop."""

    @patch("scripts.run_local_models._print_summary")
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_default_iterations_runs_once(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """iterations=1 (default) runs the cycle exactly once."""
        had_failure = run_iteration_loop(_ITER_CONFIG, iterations=1)
        assert mock_run.call_count == 1
        assert not had_failure

    @patch("scripts.run_local_models._print_summary")
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_finite_iterations(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """iterations=3 runs the cycle exactly 3 times."""
        had_failure = run_iteration_loop(_ITER_CONFIG, iterations=3)
        assert mock_run.call_count == 3
        assert mock_discover.call_count == 3
        assert not had_failure

    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.run_model_suites")
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_stop_on_error_stops_after_failure(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """iterations=0 (stop-on-error) stops after a pass with failures."""
        mock_run.side_effect = [_make_pass_result(), _make_fail_result()]
        had_failure = run_iteration_loop(_ITER_CONFIG, iterations=0)
        assert mock_run.call_count == 2
        assert had_failure

    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.run_model_suites")
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_stop_on_error_continues_while_passing(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """iterations=0 keeps going while all passes succeed, then stops on failure."""
        mock_run.side_effect = [
            _make_pass_result(),
            _make_pass_result(),
            _make_pass_result(),
            _make_fail_result(),
        ]
        had_failure = run_iteration_loop(_ITER_CONFIG, iterations=0)
        assert mock_run.call_count == 4
        assert had_failure

    @patch("scripts.run_local_models._print_summary")
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_infinite_iterations_runs_until_interrupted(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """iterations=-1 runs until KeyboardInterrupt."""
        # Simulate KeyboardInterrupt after 3 passes
        mock_run.side_effect = [
            _make_pass_result(),
            _make_pass_result(),
            KeyboardInterrupt,
        ]
        had_failure = run_iteration_loop(_ITER_CONFIG, iterations=-1)
        assert mock_run.call_count == 3
        assert not had_failure

    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.run_model_suites")
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_infinite_iterations_continues_on_failure(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """iterations=-1 keeps running even when tests fail."""
        mock_run.side_effect = [
            _make_fail_result(),
            _make_pass_result(),
            KeyboardInterrupt,
        ]
        had_failure = run_iteration_loop(_ITER_CONFIG, iterations=-1)
        assert mock_run.call_count == 3
        assert had_failure

    @patch("scripts.run_local_models._print_summary")
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_rediscovers_each_iteration(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """Each iteration re-discovers nodes/models (nodes may change)."""
        run_iteration_loop(_ITER_CONFIG, iterations=3)
        assert mock_discover.call_count == 3


# ---------------------------------------------------------------------------
# verify_db_results
# ---------------------------------------------------------------------------

_SAMPLE_RESULTS = [
    RunResult(node="host1", model="llama3", suite="math", returncode=0, output_dir="r/h/m"),
    RunResult(node="host1", model="mistral", suite="math", returncode=0, output_dir="r/h/m2"),
]


def _recent_timestamp() -> str:
    """Return an ISO timestamp from a few minutes ago."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(tz=timezone.utc) - timedelta(minutes=2)).isoformat()


class TestVerifyDbResults:
    """Tests for verify_db_results() — post-run DB confirmation."""

    def test_skips_on_dry_run(self) -> None:
        """Dry-run mode should skip DB check entirely and return True."""
        assert verify_db_results(_SAMPLE_RESULTS, dry_run=True) is True

    def test_skips_when_no_results(self) -> None:
        """No results means nothing to verify."""
        assert verify_db_results([], dry_run=False) is True

    @patch.dict("os.environ", {}, clear=True)
    def test_skips_when_no_database_url(self) -> None:
        """Without DATABASE_URL, skip gracefully and return True."""
        # Ensure DATABASE_URL is not set
        import os

        os.environ.pop("DATABASE_URL", None)
        assert verify_db_results(_SAMPLE_RESULTS) is True

    @patch("rfc.test_database.TestDatabase")
    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://rfc:pass@db:5433/rfc"})
    def test_passes_when_recent_runs_found(self, mock_db_cls: MagicMock) -> None:
        """Returns True when DB has recent runs matching expected count."""
        mock_db = mock_db_cls.return_value
        mock_db.get_recent_runs.return_value = [
            {"id": 1, "timestamp": _recent_timestamp(), "model_name": "llama3"},
            {"id": 2, "timestamp": _recent_timestamp(), "model_name": "mistral"},
        ]
        assert verify_db_results(_SAMPLE_RESULTS) is True

    @patch("rfc.test_database.TestDatabase")
    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://rfc:pass@db:5433/rfc"})
    def test_fails_when_no_recent_runs(self, mock_db_cls: MagicMock) -> None:
        """Returns False (hard failure) when DB has zero recent runs."""
        mock_db = mock_db_cls.return_value
        mock_db.get_recent_runs.return_value = []
        assert verify_db_results(_SAMPLE_RESULTS) is False

    @patch("rfc.test_database.TestDatabase")
    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://rfc:pass@db:5433/rfc"})
    def test_warns_on_partial_archival(self, mock_db_cls: MagicMock) -> None:
        """Partial archival (some rows, not all) returns True with warning."""
        mock_db = mock_db_cls.return_value
        mock_db.get_recent_runs.return_value = [
            {"id": 1, "timestamp": _recent_timestamp(), "model_name": "llama3"},
        ]
        # 2 results expected but only 1 in DB — still True (partial is not hard fail)
        assert verify_db_results(_SAMPLE_RESULTS) is True

    @patch("rfc.test_database.TestDatabase")
    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://rfc:pass@db:5433/rfc"})
    def test_handles_db_connection_error(self, mock_db_cls: MagicMock) -> None:
        """DB connection failure returns False (hard failure)."""
        mock_db_cls.side_effect = Exception("Connection refused")
        assert verify_db_results(_SAMPLE_RESULTS) is False
