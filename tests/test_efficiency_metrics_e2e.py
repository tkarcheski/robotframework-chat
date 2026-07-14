"""End-to-end adversarial checks for the RFC-010 S1 efficiency metrics (#258).

Added during the test-design verdict on PR #298. Each test drives a real
``python -m robot`` subprocess (no LLM; synthetic payloads in the exact
production wire shapes) and asserts what actually lands in
``agentic_metrics``:

- a mixed hit/miss suite records the exact per-suite rate (3 of 5 = 0.6),
  with hits shaped like ``answer_cache._cache_hit_metrics`` (zero counts,
  null rates) so the parser's acceptance of real hit payloads is proven
- ``suite_runtime_ms`` is wall time — a sleeping suite registers its sleep
- a suite with zero ``generate()`` calls records NO ``cache_hit_rate`` row
  (omitted, not a diluting 0.0) while still recording its runtime
- a nested directory run emits the efficiency pair exactly once (top-level
  suite only), with the rate aggregated across the child suites
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rfc.harness_listener_kw import HarnessListenerRunner

_SUITE_HEADER = """\
*** Settings ***
Library    rfc.rfc_data

*** Test Cases ***
"""

# The exact wire shape answer_cache.CachingProvider stamps on a hit
# (see answer_cache._cache_hit_metrics): zero counts, null rates.
_HIT_PAYLOAD = json.dumps(
    {
        "model_name": "test-model",
        "cache_hit": True,
        "total_duration_ns": 0,
        "load_duration_ns": 0,
        "prompt_eval_count": 0,
        "prompt_eval_duration_ns": 0,
        "prompt_eval_rate": None,
        "eval_count": 0,
        "eval_duration_ns": 0,
        "eval_rate": None,
    }
)

# A fresh-generation (miss) payload in the Ollama shape the runner uses.
_MISS_PAYLOAD = json.dumps(
    {
        "prompt_eval_count": 100,
        "eval_count": 40,
        "total_duration_ns": 2_500_000_000,
    }
)


@pytest.fixture()
def runner():
    return HarnessListenerRunner()


@pytest.fixture()
def workspace(runner, tmp_path):
    return runner.create_listener_workspace(str(tmp_path))


def _write_suite(path: Path, *test_bodies: list[str]) -> None:
    """Write a Robot suite file with one ``Inner Test`` per body."""
    lines = [_SUITE_HEADER]
    for index, body in enumerate(test_bodies, start=1):
        lines.append(f"Inner Test {index}")
        lines.extend(body)
        lines.append("")
    path.write_text("\n".join(lines))


def _emit(payload: str) -> list[str]:
    return [f"    Emit Rfc Data    llm_metrics    {payload}"]


def _run_robot(runner, workspace, target: str) -> None:
    """Run *target* with the listener attached, as run_inner_suite does."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "robot",
            "--listener",
            "rfc.agentic_harness_listener.AgenticHarnessListener",
            "--outputdir",
            str(Path(workspace["path"]) / "robot-output"),
            target,
        ],
        cwd=workspace["path"],
        env=runner._subprocess_env(workspace),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def _rows(runner, workspace, session_id: str, key: str) -> list[float]:
    return [
        r["metric_value"]
        for r in runner.get_metric_rows(workspace, session_id, metric_key=key)
    ]


class TestCacheHitRateHonesty:
    def test_mixed_hit_miss_rate_is_exact(self, runner, workspace, tmp_path):
        """3 production-shaped hits out of 5 calls -> exactly one 0.6 row."""
        session_id = runner.start_harness_session(workspace)
        _write_suite(
            tmp_path / "inner_suite.robot",
            _emit(_HIT_PAYLOAD),
            _emit(_HIT_PAYLOAD),
            _emit(_HIT_PAYLOAD),
            _emit(_MISS_PAYLOAD),
            _emit(_MISS_PAYLOAD),
        )
        _run_robot(runner, workspace, "inner_suite.robot")
        assert _rows(runner, workspace, session_id, "cache_hit_rate") == [0.6]

    def test_zero_generate_suite_omits_cache_hit_rate(
        self, runner, workspace, tmp_path
    ):
        """No generate() calls -> NO rate row (not a diluting 0.0); runtime lands."""
        session_id = runner.start_harness_session(workspace)
        _write_suite(tmp_path / "inner_suite.robot", ["    No Operation"])
        _run_robot(runner, workspace, "inner_suite.robot")
        assert _rows(runner, workspace, session_id, "cache_hit_rate") == []
        runtimes = _rows(runner, workspace, session_id, "suite_runtime_ms")
        assert len(runtimes) == 1 and runtimes[0] > 0

    def test_nested_run_emits_pair_once_aggregated(self, runner, workspace, tmp_path):
        """A directory run: one rate row (0.5 across children), one runtime row."""
        session_id = runner.start_harness_session(workspace)
        nested = tmp_path / "nested"
        nested.mkdir()
        _write_suite(nested / "suite_a.robot", _emit(_HIT_PAYLOAD))
        _write_suite(nested / "suite_b.robot", _emit(_MISS_PAYLOAD))
        _run_robot(runner, workspace, "nested")
        assert _rows(runner, workspace, session_id, "cache_hit_rate") == [0.5]
        assert len(_rows(runner, workspace, session_id, "suite_runtime_ms")) == 1


class TestSuiteRuntimeIsWallTime:
    def test_sleeping_suite_registers_wall_time(self, runner, workspace, tmp_path):
        """A `Sleep 2s` test must land >= 2000 ms — wall clock, not cpu."""
        session_id = runner.start_harness_session(workspace)
        _write_suite(tmp_path / "inner_suite.robot", ["    Sleep    2s"])
        _run_robot(runner, workspace, "inner_suite.robot")
        runtimes = _rows(runner, workspace, session_id, "suite_runtime_ms")
        assert len(runtimes) == 1
        assert runtimes[0] >= 2000
        assert runtimes[0] < 120_000  # sanity: still a real per-suite figure
