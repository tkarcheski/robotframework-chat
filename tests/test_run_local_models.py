"""Tests for scripts/run_local_models.py — local model runner."""

from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from rfc.host_scheduler import HostConfig, HostSpec, SchedulerDefaults
from scripts.run_local_models import (
    PREFLIGHT_SUITE,
    RunResult,
    _build_robot_command,
    _maybe_audit,
    _nodes_from_host_config,
    _sanitize_name,
    discover_local_models,
    load_local_config,
    preflight_model,
    run_iteration_loop,
    run_model_suites,
    verify_db_results,
)


class TestMaybeAudit:
    """The post-run coverage audit hook must be optional and non-fatal."""

    def test_skips_on_dry_run(self) -> None:
        with patch("scripts.audit_robot_reports.run_audit") as run_audit:
            _maybe_audit(dry_run=True, audit=True)
        run_audit.assert_not_called()

    def test_skips_when_disabled(self) -> None:
        with patch("scripts.audit_robot_reports.run_audit") as run_audit:
            _maybe_audit(dry_run=False, audit=False)
        run_audit.assert_not_called()

    def test_runs_and_commits_when_enabled(self) -> None:
        with patch("scripts.audit_robot_reports.run_audit") as run_audit:
            _maybe_audit(dry_run=False, audit=True)
        run_audit.assert_called_once()
        assert run_audit.call_args.kwargs["commit"] is True

    def test_swallows_audit_errors(self) -> None:
        # A failing audit must never propagate and kill a multi-hour run.
        with patch(
            "scripts.audit_robot_reports.run_audit",
            side_effect=RuntimeError("boom"),
        ):
            _maybe_audit(dry_run=False, audit=True)  # must not raise


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
    @patch("scripts.run_local_models._query_loaded_models", return_value=[])
    @patch("scripts.run_local_models._query_models", return_value=["llama3", "mistral"])
    @patch("scripts.run_local_models._probe_port", return_value=True)
    def test_discovers_from_node_list(
        self, mock_probe: MagicMock, mock_models: MagicMock, mock_loaded: MagicMock
    ) -> None:
        nodes = [
            {"hostname": "host1", "port": 11434},
        ]
        result = discover_local_models(nodes)
        assert len(result) == 1
        assert result[0]["endpoint"] == "http://host1:11434"
        assert result[0]["models"] == ["llama3", "mistral"]

    @patch("scripts.run_local_models._query_loaded_models", return_value=["mistral"])
    @patch("scripts.run_local_models._query_models", return_value=["llama3", "mistral"])
    @patch("scripts.run_local_models._probe_port", return_value=True)
    def test_reports_loaded_models_from_api_ps(
        self, mock_probe: MagicMock, mock_models: MagicMock, mock_loaded: MagicMock
    ) -> None:
        """discover_local_models must surface /api/ps state for the scheduler."""
        result = discover_local_models([{"hostname": "host1", "port": 11434}])
        assert result[0]["loaded_models"] == ["mistral"]

    @patch("scripts.run_local_models._query_loaded_models", return_value=[])
    @patch("scripts.run_local_models._query_models", return_value=["llama3"])
    @patch("scripts.run_local_models._probe_port", return_value=True)
    def test_carries_host_config_fields_through(
        self, mock_probe: MagicMock, mock_models: MagicMock, mock_loaded: MagicMock
    ) -> None:
        """TOML-sourced node attributes survive discovery for the scheduler."""
        nodes = [
            {
                "hostname": "host1",
                "port": 11434,
                "name": "gpu-rig",
                "priority": 20,
                "max_parallel": 2,
                "skip_models": ["big:70b"],
            },
        ]
        result = discover_local_models(nodes)
        assert result[0]["name"] == "gpu-rig"
        assert result[0]["priority"] == 20
        assert result[0]["max_parallel"] == 2
        assert result[0]["skip_models"] == ["big:70b"]

    @patch("scripts.run_local_models._probe_port", return_value=False)
    def test_skips_offline_nodes(self, mock_probe: MagicMock) -> None:
        nodes = [{"hostname": "offline", "port": 11434}]
        result = discover_local_models(nodes)
        assert result == []

    def test_empty_nodes(self) -> None:
        result = discover_local_models([])
        assert result == []

    @patch("scripts.run_local_models._query_loaded_models", return_value=[])
    @patch("scripts.run_local_models._query_models", return_value=[])
    @patch("scripts.run_local_models._probe_port", return_value=True)
    def test_online_but_no_models(
        self, mock_probe: MagicMock, mock_models: MagicMock, mock_loaded: MagicMock
    ) -> None:
        nodes = [{"hostname": "empty", "port": 11434}]
        result = discover_local_models(nodes)
        # Node is online but has no models — still included so user sees it
        assert len(result) == 1
        assert result[0]["models"] == []


class TestNodesFromHostConfig:
    """TOML host entries become probe-able node dicts with scheduler fields."""

    def test_converts_hosts_to_nodes(self) -> None:
        host_config = HostConfig(
            hosts=[
                HostSpec(
                    name="gpu-rig",
                    endpoint="http://192.168.1.20:11434",
                    priority=20,
                    max_parallel=2,
                    skip_models=["big:70b"],
                ),
            ],
            defaults=SchedulerDefaults(),
        )
        nodes = _nodes_from_host_config(host_config)
        assert nodes == [
            {
                "hostname": "192.168.1.20",
                "port": 11434,
                "name": "gpu-rig",
                "priority": 20,
                "max_parallel": 2,
                "skip_models": ["big:70b"],
            }
        ]

    def test_default_port_when_missing(self) -> None:
        host_config = HostConfig(
            hosts=[HostSpec(name="h", endpoint="http://myhost")],
            defaults=SchedulerDefaults(),
        )
        nodes = _nodes_from_host_config(host_config)
        assert nodes[0]["hostname"] == "myhost"
        assert nodes[0]["port"] == 11434


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
    def test_prioritizes_loaded_models(self, mock_run: MagicMock) -> None:
        """Models loaded per /api/ps run before cold models (no shuffle)."""
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
            },
        }
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["alpha", "bravo", "charlie"],
                "loaded_models": ["charlie"],
            },
        ]
        results = run_model_suites(config, nodes_with_models)
        executed_models = [r.model for r in results]
        assert executed_models[0] == "charlie"
        assert sorted(executed_models) == ["alpha", "bravo", "charlie"]

    @patch("scripts.run_local_models.subprocess.run")
    def test_deduplicates_models_across_hosts(self, mock_run: MagicMock) -> None:
        """A model available on multiple hosts runs once per suite (global queue)."""
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
            },
        }
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["shared", "only1"],
            },
            {
                "endpoint": "http://host2:11434",
                "hostname": "host2",
                "models": ["shared"],
            },
        ]
        results = run_model_suites(config, nodes_with_models)
        executed = sorted(r.model for r in results)
        assert executed == ["only1", "shared"]

    @patch("scripts.run_local_models.subprocess.run")
    def test_skip_models_not_run_on_skipping_host(self, mock_run: MagicMock) -> None:
        """skip_models excludes a model from a host; unschedulable jobs are dropped."""
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
            },
        }
        nodes_with_models = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["big", "small"],
                "skip_models": ["big"],
            },
        ]
        results = run_model_suites(config, nodes_with_models)
        assert [r.model for r in results] == ["small"]

    @patch("scripts.run_local_models.subprocess.run")
    def test_does_not_mutate_input(self, mock_run: MagicMock) -> None:
        """Scheduling must not mutate the original nodes_with_models."""
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


class TestPreflightModel:
    """preflight_model() probes a model with one tiny prompt (issue #426)."""

    @patch("scripts.run_local_models.requests.post")
    def test_ok_on_nonempty_response(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"response": "ok"}
        )
        ok, reason = preflight_model("http://host1:11434", "llama3")
        assert ok
        assert reason == "ok"

    @patch("scripts.run_local_models.requests.post")
    def test_fails_on_empty_response(self, mock_post: MagicMock) -> None:
        """An HTTP 200 with an empty/whitespace response body is a failure
        (the glm-4.7-flash:q8_0 symptom from issue #426)."""
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"response": "   "}
        )
        ok, reason = preflight_model("http://host1:11434", "glm-4.7-flash:q8_0")
        assert not ok
        assert "empty" in reason

    @patch("scripts.run_local_models.requests.post")
    def test_fails_on_request_exception(self, mock_post: MagicMock) -> None:
        import requests as _requests

        mock_post.side_effect = _requests.ConnectionError("connection refused")
        ok, reason = preflight_model("http://host1:11434", "llama3")
        assert not ok
        assert "connection refused" in reason

    @patch("scripts.run_local_models.requests.post")
    def test_fails_on_http_error(self, mock_post: MagicMock) -> None:
        import requests as _requests

        resp = MagicMock(status_code=500)
        resp.raise_for_status.side_effect = _requests.HTTPError("500 Server Error")
        mock_post.return_value = resp
        ok, reason = preflight_model("http://host1:11434", "llama3")
        assert not ok

    @patch("scripts.run_local_models.requests.post")
    def test_fails_on_invalid_json(self, mock_post: MagicMock) -> None:
        resp = MagicMock(status_code=200)
        resp.json.side_effect = ValueError("not json")
        mock_post.return_value = resp
        ok, reason = preflight_model("http://host1:11434", "llama3")
        assert not ok

    @patch("scripts.run_local_models.requests.post")
    def test_sends_model_and_no_stream(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"response": "ok"}
        )
        preflight_model("http://host1:11434", "llama3", timeout=42)
        kwargs = mock_post.call_args.kwargs
        assert kwargs["json"]["model"] == "llama3"
        assert kwargs["json"]["stream"] is False
        assert kwargs["timeout"] == 42


def _preflight_config(*, preflight: bool = True) -> dict:
    return {
        "test_suites": [
            {"name": "math", "path": "robot/math/tests/", "timeout_seconds": 300},
        ],
        "execution": {
            "output_dir": "results/local/{node}/{model}",
            "extra_args": [],
            "listeners": [],
            "continue_on_failure": True,
            "parallel": 1,
            "preflight": preflight,
            "preflight_timeout": 60,
        },
    }


class TestRunModelSuitesPreflight:
    """A model that fails preflight is recorded and skipped — the run
    continues with the next model (issue #426)."""

    @patch("scripts.run_local_models.preflight_model")
    @patch("scripts.run_local_models.subprocess.run")
    def test_bad_model_skipped_run_continues(
        self, mock_run: MagicMock, mock_preflight: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        # First model fails preflight, second passes.
        mock_preflight.side_effect = [
            (False, "empty response"),
            (True, "ok"),
        ]
        nodes = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["badmodel", "goodmodel"],
            },
        ]
        results = run_model_suites(_preflight_config(), nodes)

        # One preflight-failure record + one real suite run.
        assert len(results) == 2
        assert results[0].model == "badmodel"
        assert results[0].suite == PREFLIGHT_SUITE
        assert results[0].returncode != 0
        assert results[1].model == "goodmodel"
        assert results[1].suite == "math"
        assert results[1].returncode == 0
        # Suites only executed for the good model.
        assert mock_run.call_count == 1

    @patch("scripts.run_local_models.preflight_model")
    @patch("scripts.run_local_models.subprocess.run")
    def test_preflight_disabled_not_called(
        self, mock_run: MagicMock, mock_preflight: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        nodes = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["llama3"],
            },
        ]
        results = run_model_suites(_preflight_config(preflight=False), nodes)
        mock_preflight.assert_not_called()
        assert len(results) == 1
        assert mock_run.call_count == 1

    @patch("scripts.run_local_models.preflight_model")
    @patch("scripts.run_local_models.subprocess.run")
    def test_dry_run_skips_preflight(
        self, mock_run: MagicMock, mock_preflight: MagicMock
    ) -> None:
        nodes = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["llama3"],
            },
        ]
        results = run_model_suites(_preflight_config(), nodes, dry_run=True)
        mock_preflight.assert_not_called()
        mock_run.assert_not_called()
        assert len(results) == 1

    @patch("scripts.run_local_models.preflight_model")
    @patch("scripts.run_local_models.subprocess.run")
    def test_preflight_timeout_from_config(
        self, mock_run: MagicMock, mock_preflight: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_preflight.return_value = (True, "ok")
        nodes = [
            {
                "endpoint": "http://host1:11434",
                "hostname": "host1",
                "models": ["llama3"],
            },
        ]
        run_model_suites(_preflight_config(), nodes)
        assert mock_preflight.call_args.kwargs["timeout"] == 60


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
    @patch("scripts.run_local_models.verify_db_results", return_value=True)
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
        mock_verify_db: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """iterations=1 (default) runs the cycle exactly once."""
        had_failure = run_iteration_loop(_ITER_CONFIG, iterations=1)
        assert mock_run.call_count == 1
        assert not had_failure

    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.verify_db_results", return_value=True)
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
        mock_verify_db: MagicMock,
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
    @patch("scripts.run_local_models.verify_db_results", return_value=True)
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
        mock_verify_db: MagicMock,
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

    @patch("scripts.run_local_models._maybe_audit")
    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.verify_db_results", return_value=True)
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch("scripts.run_local_models.discover_local_models")
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_audit_runs_after_first_executed_pass_not_iteration_one(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_verify_db: MagicMock,
        mock_summary: MagicMock,
        mock_audit: MagicMock,
    ) -> None:
        """When the first iteration discovers no models it `continue`s early, so
        gating the audit on iteration == 1 would skip it forever. The audit must
        fire on the first iteration that actually runs tests."""
        # Iteration 1: no models (total_runs == 0 → continue). Iteration 2: runs.
        mock_discover.side_effect = [[], _ITER_DISCOVERED]
        run_iteration_loop(_ITER_CONFIG, iterations=2)
        assert mock_run.call_count == 1  # only the 2nd iteration ran tests
        mock_audit.assert_called_once()

    @patch("scripts.run_local_models._maybe_audit")
    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.verify_db_results", return_value=True)
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_audit_runs_once_across_multiple_passes(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_verify_db: MagicMock,
        mock_summary: MagicMock,
        mock_audit: MagicMock,
    ) -> None:
        """The audit fires once per invocation, not once per pass."""
        run_iteration_loop(_ITER_CONFIG, iterations=3)
        assert mock_run.call_count == 3
        mock_audit.assert_called_once()

    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.verify_db_results", return_value=True)
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list")
    def test_toml_mode_uses_host_config_not_env(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_verify_db: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """mode='toml' sources nodes from host-config, not env discovery, and
        passes the TOML global_max_parallel to the scheduler."""
        host_config = HostConfig(
            hosts=[HostSpec(name="h1", endpoint="http://host1:11434", priority=5)],
            defaults=SchedulerDefaults(global_max_parallel=3),
        )
        run_iteration_loop(
            _ITER_CONFIG,
            iterations=1,
            audit=False,
            mode="toml",
            host_config=host_config,
        )
        mock_nodes.assert_not_called()
        probed = mock_discover.call_args.args[0]
        assert probed[0]["hostname"] == "host1"
        assert probed[0]["name"] == "h1"
        assert mock_run.call_args.kwargs["global_max_parallel"] == 3

    @patch("scripts.run_local_models._print_summary")
    @patch("scripts.run_local_models.verify_db_results", return_value=True)
    @patch(
        "scripts.run_local_models.run_model_suites", return_value=_make_pass_result()
    )
    @patch(
        "scripts.run_local_models.discover_local_models", return_value=_ITER_DISCOVERED
    )
    @patch("scripts.run_local_models._load_node_list", return_value=_ITER_NODES)
    def test_external_mode_honors_execution_parallel(
        self,
        mock_nodes: MagicMock,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_verify_db: MagicMock,
        mock_summary: MagicMock,
    ) -> None:
        """mode='external' keeps env discovery and uses execution.parallel."""
        config = copy.deepcopy(_ITER_CONFIG)
        config["execution"]["parallel"] = 2
        run_iteration_loop(config, iterations=1, audit=False, mode="external")
        mock_nodes.assert_called_once()
        assert mock_run.call_args.kwargs["global_max_parallel"] == 2


# ---------------------------------------------------------------------------
# verify_db_results
# ---------------------------------------------------------------------------

_SAMPLE_RESULTS = [
    RunResult(
        node="host1", model="llama3", suite="math", returncode=0, output_dir="r/h/m"
    ),
    RunResult(
        node="host1", model="mistral", suite="math", returncode=0, output_dir="r/h/m2"
    ),
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


# ---------------------------------------------------------------------------
# External providers (issue #507)
# ---------------------------------------------------------------------------

from rfc.providers import ProviderConfig  # noqa: E402

from scripts.run_local_models import (  # noqa: E402
    _build_provider_robot_command,
    run_provider_runs,
    run_provider_suites,
)


def _provider(**overrides: object) -> ProviderConfig:
    kwargs: dict[str, object] = dict(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
    )
    kwargs.update(overrides)
    return ProviderConfig(**kwargs)  # type: ignore[arg-type]


def _provider_config() -> dict:
    return {
        "test_suites": [
            {"name": "math", "path": "robot/math/", "timeout_seconds": 300},
            {"name": "safety", "path": "robot/safety/", "timeout_seconds": 300},
        ],
        "execution": {
            "output_dir": "results/local/{node}/{model}",
            "extra_args": [],
            "listeners": ["rfc.db_listener.DbListener"],
            "continue_on_failure": True,
        },
        "providers": [
            {
                "name": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "discover_free_pool": True,
            }
        ],
    }


class TestBuildProviderRobotCommand:
    def test_basic_command(self) -> None:
        config = _provider_config()
        cmd = _build_provider_robot_command(
            config=config,
            suite=config["test_suites"][0],
            provider=_provider(),
            model="meta-llama/llama-3.3-70b-instruct:free",
        )
        assert cmd[:3] == ["uv", "run", "robot"]
        assert "rfc.db_listener.DbListener" in cmd
        # Raw model id goes to the Robot variable (the API needs it verbatim)
        assert any(
            "DEFAULT_MODEL:meta-llama/llama-3.3-70b-instruct:free" in a for a in cmd
        )
        # No Ollama endpoint override for provider runs
        assert not any("OLLAMA_ENDPOINT" in a for a in cmd)
        assert "robot/math/" in cmd

    def test_output_dir_uses_provider_as_node(self) -> None:
        config = _provider_config()
        cmd = _build_provider_robot_command(
            config=config,
            suite=config["test_suites"][0],
            provider=_provider(),
            model="qwen/qwen3-32b:free",
        )
        d_idx = cmd.index("-d")
        assert cmd[d_idx + 1] == "results/local/openrouter/qwen_qwen3-32b_free"


class TestRunProviderSuites:
    @patch("scripts.run_local_models.subprocess.run")
    def test_runs_all_suites_for_all_models(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        results = run_provider_suites(
            _provider_config(),
            _provider(),
            "sk-or-abc",
            ["a/b:free", "c/d:free"],
            sleep_fn=lambda _s: None,
        )
        assert len(results) == 4  # 2 models x 2 suites
        assert mock_run.call_count == 4

    @patch("scripts.run_local_models.subprocess.run")
    def test_subprocess_env_selects_openai_provider(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        run_provider_suites(
            _provider_config(),
            _provider(),
            "sk-or-abc",
            ["meta-llama/llama-3.3-70b-instruct:free"],
            sleep_fn=lambda _s: None,
        )
        env = mock_run.call_args.kwargs.get("env")
        assert env is not None
        assert env["LLM_PROVIDER"] == "openai"
        assert env["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
        assert env["OPENAI_API_KEY"] == "sk-or-abc"
        # Raw id for the API; prefixed watermark for attribution (#507)
        assert env["DEFAULT_MODEL"] == "meta-llama/llama-3.3-70b-instruct:free"
        assert (
            env["RFC_MODEL_NAME"] == "openrouter/meta-llama/llama-3.3-70b-instruct:free"
        )

    @patch("scripts.run_local_models.subprocess.run")
    def test_results_attributed_with_provider_prefix(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        results = run_provider_suites(
            _provider_config(),
            _provider(),
            "sk-or-abc",
            ["a/b:free"],
            sleep_fn=lambda _s: None,
        )
        assert all(r.node == "openrouter" for r in results)
        assert all(r.model == "openrouter/a/b:free" for r in results)
        assert {r.suite for r in results} == {"math", "safety"}

    @patch("scripts.run_local_models.subprocess.run")
    def test_rpm_pacing_sleeps_between_jobs(self, mock_run: MagicMock) -> None:
        """Consecutive jobs are paced to honor requests_per_minute."""
        mock_run.return_value = MagicMock(returncode=0)
        sleeps: list[float] = []
        provider = _provider(requests_per_minute=20, requests_per_suite_estimate=20)
        run_provider_suites(
            _provider_config(),
            provider,
            "sk-or-abc",
            ["a/b:free"],
            sleep_fn=sleeps.append,
        )
        # 2 suites -> one pacing gap; ~20 requests at 20 RPM needs ~60s budget
        assert len(sleeps) == 1
        assert 0 < sleeps[0] <= 60.0

    @patch("scripts.run_local_models.subprocess.run")
    def test_dry_run_prints_commands_without_executing(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        results = run_provider_suites(
            _provider_config(),
            _provider(),
            "sk-or-abc",
            ["a/b:free"],
            dry_run=True,
            sleep_fn=lambda _s: None,
        )
        mock_run.assert_not_called()
        assert len(results) == 2
        assert "[DRY-RUN]" in capsys.readouterr().out

    @patch("scripts.run_local_models.subprocess.run")
    def test_dry_run_does_not_print_api_key(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run_provider_suites(
            _provider_config(),
            _provider(),
            "sk-or-SECRET",
            ["a/b:free"],
            dry_run=True,
            sleep_fn=lambda _s: None,
        )
        assert "sk-or-SECRET" not in capsys.readouterr().out

    @patch("scripts.run_local_models.subprocess.run")
    def test_failed_job_does_not_abort_provider_sweep(
        self, mock_run: MagicMock
    ) -> None:
        """A 429-exhausted (or otherwise failed) suite run is skip-and-log:
        the remaining suites and models must still run (#507)."""
        mock_run.side_effect = [
            MagicMock(returncode=1),  # first job fails (e.g. exhausted 429)
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        results = run_provider_suites(
            _provider_config(),
            _provider(),
            "sk-or-abc",
            ["a/b:free", "c/d:free"],
            sleep_fn=lambda _s: None,
        )
        assert mock_run.call_count == 4  # 2 models x 2 suites, no abort
        assert [r.returncode for r in results] == [1, 0, 0, 0]
        assert results[0].model == "openrouter/a/b:free"


class TestRunProviderRuns:
    def test_no_providers_configured_is_noop(self) -> None:
        config = _provider_config()
        del config["providers"]
        assert run_provider_runs(config) == []

    def test_key_absent_skips_provider_with_log(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import os as _os

        env = {k: v for k, v in _os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict(_os.environ, env, clear=True):
            results = run_provider_runs(_provider_config())
        assert results == []
        out = capsys.readouterr().out
        assert "OPENROUTER_API_KEY" in out
        assert "skipping" in out.lower()

    @patch("scripts.run_local_models.run_provider_suites", return_value=[])
    @patch(
        "scripts.run_local_models.discover_free_models",
        return_value=["a/b:free", "c/d:free"],
    )
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-abc"})
    def test_discovers_free_pool_and_runs(
        self, mock_discover: MagicMock, mock_suites: MagicMock
    ) -> None:
        run_provider_runs(_provider_config())
        mock_discover.assert_called_once()
        mock_suites.assert_called_once()
        models = mock_suites.call_args.args[3]
        assert models == ["a/b:free", "c/d:free"]

    @patch("scripts.run_local_models.run_provider_suites", return_value=[])
    @patch(
        "scripts.run_local_models.discover_free_models",
        side_effect=Exception("api down"),
    )
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-abc"})
    def test_discovery_failure_skips_and_logs(
        self,
        mock_discover: MagicMock,
        mock_suites: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        results = run_provider_runs(_provider_config())
        assert results == []
        mock_suites.assert_not_called()
        out = capsys.readouterr().out
        assert "skipping" in out.lower()

    @patch("scripts.run_local_models.run_provider_suites", return_value=[])
    @patch("scripts.run_local_models.discover_free_models")
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-abc"})
    def test_budget_caps_scheduled_models(
        self, mock_discover: MagicMock, mock_suites: MagicMock
    ) -> None:
        # 3 models x 2 suites x 100 req/suite = 600; budget 400 -> 2 models
        mock_discover.return_value = ["a:free", "b:free", "c:free"]
        config = _provider_config()
        config["providers"][0]["max_requests_per_day"] = 400
        config["providers"][0]["requests_per_suite_estimate"] = 100
        run_provider_runs(config)
        models = mock_suites.call_args.args[3]
        assert models == ["a:free", "b:free"]

    @patch("scripts.run_local_models.run_provider_suites", return_value=[])
    @patch("scripts.run_local_models.discover_free_models")
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-abc"})
    def test_static_models_combined_with_free_pool_deduped(
        self, mock_discover: MagicMock, mock_suites: MagicMock
    ) -> None:
        mock_discover.return_value = ["a:free", "b:free"]
        config = _provider_config()
        config["providers"][0]["models"] = ["a:free", "x/y"]
        run_provider_runs(config)
        models = mock_suites.call_args.args[3]
        assert models == ["a:free", "x/y", "b:free"]

    @patch("scripts.run_local_models.run_provider_suites", return_value=[])
    @patch("rfc.providers.requests.get")
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-abc"})
    def test_models_response_with_null_data_skips_and_logs(
        self,
        mock_get: MagicMock,
        mock_suites: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A /models body of {"data": null} must skip-and-log, not crash (#507).

        discover_free_models raises TypeError here (outside its documented
        RequestException contract); the runner's broad discovery guard must
        still contain it.
        """
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"data": None})
        )
        results = run_provider_runs(_provider_config())
        assert results == []
        mock_suites.assert_not_called()
        out = capsys.readouterr().out
        assert "free-pool discovery failed" in out
        assert "skip" in out.lower()

    @patch("scripts.run_local_models.run_provider_suites", return_value=[])
    @patch("scripts.run_local_models.discover_free_models", return_value=[])
    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-abc"})
    def test_empty_free_pool_and_no_static_models_skips_provider(
        self,
        mock_discover: MagicMock,
        mock_suites: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Discovery succeeds but the pool is empty: skip with a log line."""
        results = run_provider_runs(_provider_config())
        assert results == []
        mock_suites.assert_not_called()
        assert "no models to run" in capsys.readouterr().out


class TestIterationLoopRunsProviders:
    @patch("scripts.run_local_models.run_provider_runs")
    @patch("scripts.run_local_models.discover_local_models", return_value=[])
    def test_providers_run_even_with_no_local_models(
        self, mock_discover: MagicMock, mock_providers: MagicMock
    ) -> None:
        """Provider runs must not depend on local Ollama discovery (#507)."""
        mock_providers.return_value = [
            RunResult(
                node="openrouter",
                model="openrouter/a:free",
                suite="math",
                returncode=0,
                output_dir="results/local/openrouter/a_free",
            )
        ]
        config = _provider_config()
        with patch("scripts.run_local_models.verify_db_results", return_value=True):
            had_failure = run_iteration_loop(config, iterations=1, audit=False)
        mock_providers.assert_called_once()
        assert had_failure is False

    @patch("scripts.run_local_models.run_provider_runs")
    @patch("scripts.run_local_models.discover_local_models", return_value=[])
    def test_provider_failure_marks_iteration_failed(
        self, mock_discover: MagicMock, mock_providers: MagicMock
    ) -> None:
        mock_providers.return_value = [
            RunResult(
                node="openrouter",
                model="openrouter/a:free",
                suite="math",
                returncode=1,
                output_dir="",
            )
        ]
        config = _provider_config()
        with patch("scripts.run_local_models.verify_db_results", return_value=True):
            had_failure = run_iteration_loop(config, iterations=1, audit=False)
        assert had_failure is True


class TestProviderContextCap:
    """Suites that need more context than the provider offers are skipped
    with a log line, not run (#509, Cerebras 8K cap)."""

    @patch("scripts.run_local_models.subprocess.run")
    def test_suites_exceeding_provider_context_are_skipped(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        config = _provider_config()
        config["test_suites"][0]["min_context_tokens"] = 16000  # math: too big
        provider = _provider(name="cerebras", max_context_tokens=8192)
        results = run_provider_suites(
            config, provider, "csk-abc", ["llama3.1-8b"], sleep_fn=lambda _s: None
        )
        assert [r.suite for r in results] == ["safety"]
        assert mock_run.call_count == 1
        out = capsys.readouterr().out
        assert "skip" in out.lower()
        assert "math" in out

    @patch("scripts.run_local_models.subprocess.run")
    def test_unlimited_provider_runs_everything(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        config = _provider_config()
        config["test_suites"][0]["min_context_tokens"] = 16000
        results = run_provider_suites(
            config, _provider(), "sk-or-abc", ["a/b:free"], sleep_fn=lambda _s: None
        )
        assert len(results) == 2


class TestPrivacyRoutingGuard:
    """local-only suites must never reach external providers (#512).

    Free endpoints may train on prompts; the guard is mechanical, not
    memory. Unknown privacy values fail closed (treated as local-only)."""

    @patch("scripts.run_local_models.subprocess.run")
    def test_local_only_suite_skipped_on_external_provider(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        config = _provider_config()
        config["test_suites"][0]["privacy"] = "local-only"  # math
        results = run_provider_suites(
            config, _provider(), "sk-or-abc", ["a/b:free"], sleep_fn=lambda _s: None
        )
        assert [r.suite for r in results] == ["safety"]
        assert mock_run.call_count == 1
        out = capsys.readouterr().out
        assert "local-only" in out
        assert "math" in out

    @patch("scripts.run_local_models.subprocess.run")
    def test_zdr_allowlisted_provider_may_run_local_only(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        config = _provider_config()
        config["test_suites"][0]["privacy"] = "local-only"
        provider = _provider(allow_local_only=True)
        results = run_provider_suites(
            config, provider, "sk-or-abc", ["a/b:free"], sleep_fn=lambda _s: None
        )
        assert len(results) == 2

    @patch("scripts.run_local_models.subprocess.run")
    def test_unknown_privacy_value_fails_closed(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        config = _provider_config()
        config["test_suites"][0]["privacy"] = "locale-only"  # typo
        results = run_provider_suites(
            config, _provider(), "sk-or-abc", ["a/b:free"], sleep_fn=lambda _s: None
        )
        assert [r.suite for r in results] == ["safety"]
        assert "unknown privacy" in capsys.readouterr().out.lower()

    @patch("scripts.run_local_models.subprocess.run")
    def test_public_default_runs_everywhere(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        results = run_provider_suites(
            _provider_config(),
            _provider(),
            "sk-or-abc",
            ["a/b:free"],
            sleep_fn=lambda _s: None,
        )
        assert len(results) == 2
