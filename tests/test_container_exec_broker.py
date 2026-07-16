"""Hermetic tests for the host-side ContainerExecBroker (#235).

A fake ``docker exec`` backend stands in for the container manager, so the
SandboxToolCall -> SandboxToolResult contract, the overhead instrumentation, and
the perf-budget gate all round-trip with zero Docker.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from rfc.container_exec_broker import (
    OVERHEAD_P50_BUDGET_MS,
    OVERHEAD_P95_BUDGET_MS,
    ContainerExecBroker,
    SandboxToolCall,
    SandboxToolResult,
    check_overhead_budget,
    percentile,
    read_overhead_samples,
)
from rfc.harness_models import METRIC_SANDBOX_EXEC_OVERHEAD_MS

# A timing sentinel line the in-container wrapper appends; the broker strips it
# and reads the command's own runtime from it. A fake backend that appends one
# simulates a real in-container timing so the transport-vs-runtime split is
# testable with zero Docker.
_MARKER = "__RFC_EXEC_MS__"


def _with_marker(stdout: str, inner_ms: int) -> str:
    return f"{stdout}{_MARKER}{inner_ms}\n"


class FakeExecBackend:
    """Scripted stand-in for ContainerManager.execute_command (docker exec)."""

    def __init__(self, results: list[dict] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[dict] = []

    def execute_command(self, container_id, command, timeout=30, workdir=None) -> dict:
        self.calls.append(
            {
                "container_id": container_id,
                "command": command,
                "timeout": timeout,
                "workdir": workdir,
            }
        )
        if self.results:
            return self.results.pop(0)
        return {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 1}


def _ok(stdout: str = "", exit_code: int = 0, duration_ms: float = 1.0) -> dict:
    return {
        "stdout": stdout,
        "stderr": "",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }


class TestBashDispatch:
    def test_bash_round_trip(self) -> None:
        backend = FakeExecBackend([_ok(stdout="hi\n", exit_code=0, duration_ms=7.0)])
        broker = ContainerExecBroker(backend, "cid-1")
        result = broker.dispatch(SandboxToolCall(kind="bash", payload="echo hi"))
        assert isinstance(result, SandboxToolResult)
        assert result.stdout == "hi\n"
        assert result.exit_code == 0
        assert result.duration_ms == 7.0
        # The raw shell string is carried verbatim inside the self-timing
        # wrapper, in /workspace.
        assert "echo hi" in backend.calls[0]["command"]
        assert backend.calls[0]["container_id"] == "cid-1"
        assert backend.calls[0]["workdir"] == "/workspace"

    def test_nonzero_exit_surfaces(self) -> None:
        backend = FakeExecBackend([_ok(stdout="boom", exit_code=2)])
        broker = ContainerExecBroker(backend, "cid-1")
        result = broker.dispatch(SandboxToolCall(kind="bash", payload="false"))
        assert result.exit_code == 2


class TestWriteAndEditDispatch:
    def test_write_builds_base64_write_command(self) -> None:
        backend = FakeExecBackend([_ok()])
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(
            SandboxToolCall(kind="write", payload="print('x')\n", path="pkg/mod.py")
        )
        cmd = backend.calls[0]["command"]
        # Arbitrary content survives via base64; parents are created first.
        assert "mkdir -p" in cmd
        assert "base64 -d" in cmd
        assert "/workspace/pkg/mod.py" in cmd

    def test_edit_is_whole_file_write(self) -> None:
        backend = FakeExecBackend([_ok()])
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(SandboxToolCall(kind="edit", payload="new", path="a.py"))
        cmd = backend.calls[0]["command"]
        assert "base64 -d" in cmd
        assert "/workspace/a.py" in cmd

    def test_write_without_path_raises(self) -> None:
        broker = ContainerExecBroker(FakeExecBackend(), "cid-1")
        with pytest.raises(ValueError):
            broker.dispatch(SandboxToolCall(kind="write", payload="x"))

    def test_unknown_kind_raises(self) -> None:
        broker = ContainerExecBroker(FakeExecBackend(), "cid-1")
        with pytest.raises(ValueError):
            broker.dispatch(SandboxToolCall(kind="teleport", payload="x"))


class TestOverheadInstrumentation:
    def test_overhead_sample_recorded_per_dispatch(self) -> None:
        backend = FakeExecBackend([_ok(duration_ms=1.0), _ok(duration_ms=1.0)])
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(SandboxToolCall(kind="bash", payload="echo 1"))
        broker.dispatch(SandboxToolCall(kind="bash", payload="echo 2"))
        assert len(broker.overhead_samples_ms) == 2
        assert all(sample >= 0.0 for sample in broker.overhead_samples_ms)

    def test_overhead_is_wall_minus_inner_clamped_at_zero(self) -> None:
        # An in-container runtime far larger than the (tiny, fake) wall time must
        # not record a negative overhead -- it clamps to zero.
        backend = FakeExecBackend([_ok(duration_ms=100_000.0)])
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(SandboxToolCall(kind="bash", payload="sleep 100"))
        assert broker.overhead_samples_ms == (0.0,)

    def test_metrics_sink_round_trips(self, tmp_path: Path) -> None:
        sink = tmp_path / "overhead.jsonl"
        backend = FakeExecBackend([_ok(), _ok()])
        broker = ContainerExecBroker(backend, "cid-1", metrics_sink=sink)
        broker.dispatch(SandboxToolCall(kind="bash", payload="echo 1"))
        broker.dispatch(SandboxToolCall(kind="bash", payload="echo 2"))
        samples = read_overhead_samples(sink)
        assert len(samples) == 2
        assert samples == list(broker.overhead_samples_ms)

    def test_overhead_metrics_use_reserved_key(self) -> None:
        backend = FakeExecBackend([_ok(), _ok()])
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(SandboxToolCall(kind="bash", payload="echo 1"))
        broker.dispatch(SandboxToolCall(kind="bash", payload="echo 2"))
        metrics = broker.overhead_metrics("sess-1", "2026-07-14T00:00:00Z")
        assert len(metrics) == 2
        assert all(m.metric_key == METRIC_SANDBOX_EXEC_OVERHEAD_MS for m in metrics)
        assert all(m.session_id == "sess-1" for m in metrics)


class TestPercentile:
    def test_empty_is_zero(self) -> None:
        assert percentile([], 95.0) == 0.0

    def test_single_value(self) -> None:
        assert percentile([42.0], 50.0) == 42.0

    def test_linear_interpolation(self) -> None:
        assert percentile([10.0, 20.0, 30.0, 40.0], 50.0) == 25.0

    def test_p95_near_top(self) -> None:
        samples = [float(n) for n in range(1, 101)]
        assert 95.0 <= percentile(samples, 95.0) <= 96.0


class TestBudgetGate:
    def test_within_budget(self) -> None:
        verdict = check_overhead_budget([10.0, 20.0, 30.0])
        assert verdict.within_budget
        assert verdict.n == 3
        assert verdict.p50_budget_ms == OVERHEAD_P50_BUDGET_MS
        assert verdict.p95_budget_ms == OVERHEAD_P95_BUDGET_MS

    def test_over_p95_budget_fails(self) -> None:
        # A tight p50 but a fat tail blows the p95 budget.
        samples = [10.0] * 9 + [5000.0]
        verdict = check_overhead_budget(samples)
        assert verdict.p50_ms <= verdict.p50_budget_ms
        assert verdict.p95_ms > verdict.p95_budget_ms
        assert not verdict.within_budget
        assert "OVER budget" in verdict.summary

    def test_empty_samples_are_vacuously_within(self) -> None:
        verdict = check_overhead_budget([])
        assert verdict.within_budget
        assert verdict.n == 0

    def test_read_missing_sink_is_empty(self, tmp_path: Path) -> None:
        assert read_overhead_samples(tmp_path / "nope.jsonl") == []


class TestOverheadIncludesTransport:
    """#235 B2: overhead = wall - command's OWN runtime, so transport counts."""

    def test_transport_counted_not_cancelled_by_duration(self) -> None:
        # A fast in-container command (marker says 2ms) inside a SLOW docker-exec
        # transport (backend sleeps ~40ms and reports a transport-inclusive
        # duration_ms of 42). Overhead must reflect the ~40ms transport, NOT be
        # cancelled to ~0 by subtracting the transport-inclusive duration -- that
        # was the pre-fix bug the metric existed to catch.
        class SlowBackend:
            def execute_command(self, cid, command, timeout=30, workdir=None) -> dict:
                time.sleep(0.04)
                return {
                    "stdout": _with_marker("ok\n", 2),
                    "stderr": "",
                    "exit_code": 0,
                    "duration_ms": 42,
                }

        broker = ContainerExecBroker(SlowBackend(), "cid-1")
        result = broker.dispatch(SandboxToolCall(kind="bash", payload="true"))
        assert result.stdout == "ok\n"  # sentinel stripped
        assert result.duration_ms == 2.0  # command's own runtime, from the marker
        overhead = broker.overhead_samples_ms[0]
        assert overhead >= 30.0  # ~40ms transport captured (old code recorded ~0)

    def test_marker_absent_falls_back_to_backend_duration(self) -> None:
        backend = FakeExecBackend([_ok(stdout="plain\n", duration_ms=5.0)])
        broker = ContainerExecBroker(backend, "cid-1")
        result = broker.dispatch(SandboxToolCall(kind="bash", payload="echo plain"))
        assert result.stdout == "plain\n"
        assert result.duration_ms == 5.0

    def test_negative_marker_falls_back(self) -> None:
        # date +%N unavailable -> wrapper emits -1 -> broker uses backend duration.
        backend = FakeExecBackend(
            [_ok(stdout=_with_marker("x\n", -1), duration_ms=9.0)]
        )
        broker = ContainerExecBroker(backend, "cid-1")
        result = broker.dispatch(SandboxToolCall(kind="bash", payload="true"))
        assert result.stdout == "x\n"
        assert result.duration_ms == 9.0


class TestWriteChunking:
    """#235 B3: large writes stream in chunks instead of one oversized argv."""

    def test_small_write_is_single_shot(self) -> None:
        backend = FakeExecBackend()
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(SandboxToolCall(kind="write", payload="hi", path="a.txt"))
        assert len(backend.calls) == 1  # one exec, inline
        assert "base64 -d" in backend.calls[0]["command"]

    def test_large_write_chunks_then_finalizes(self) -> None:
        backend = FakeExecBackend()
        broker = ContainerExecBroker(backend, "cid-1")
        # ~300 KB raw -> ~400 KB base64 -> several 60k chunks + one finalize.
        result = broker.dispatch(
            SandboxToolCall(kind="write", payload="A" * 300_000, path="big.txt")
        )
        assert result.exit_code == 0
        assert len(backend.calls) >= 3
        # First chunk creates the out-of-tree temp with '>'; later ones append.
        assert " > /tmp/rfc-exec-write-" in backend.calls[0]["command"]
        assert " >> /tmp/rfc-exec-write-" in backend.calls[1]["command"]
        # No single command inlines the whole base64 (each argv stays bounded).
        assert all(len(c["command"]) < 80_000 for c in backend.calls)
        # Finalize decodes into the workspace target and removes the temp.
        finalize = backend.calls[-1]["command"]
        assert "base64 -d /tmp/rfc-exec-write-" in finalize
        assert "/workspace/big.txt" in finalize
        assert "rm -f /tmp/rfc-exec-write-" in finalize

    def test_chunk_failure_aborts_and_cleans_up(self) -> None:
        # First append fails -> abort, attempt temp cleanup, surface the failure.
        backend = FakeExecBackend(
            [{"stdout": "disk full", "stderr": "", "exit_code": 1, "duration_ms": 1}]
        )
        broker = ContainerExecBroker(backend, "cid-1")
        result = broker.dispatch(
            SandboxToolCall(kind="write", payload="A" * 300_000, path="big.txt")
        )
        assert result.exit_code == 1
        assert any("rm -f /tmp/rfc-exec-write-" in c["command"] for c in backend.calls)


class TestWorkspaceConfinement:
    """#235 S1: write/edit paths must stay under /workspace."""

    def test_parent_traversal_rejected(self) -> None:
        broker = ContainerExecBroker(FakeExecBackend(), "cid-1")
        with pytest.raises(ValueError, match="escapes"):
            broker.dispatch(
                SandboxToolCall(kind="write", payload="x", path="../../etc/passwd")
            )

    def test_absolute_path_rerooted_into_workspace(self) -> None:
        backend = FakeExecBackend()
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(SandboxToolCall(kind="write", payload="x", path="/etc/PWNED"))
        assert any("/workspace/etc/PWNED" in c["command"] for c in backend.calls)

    def test_legit_nested_path_ok(self) -> None:
        backend = FakeExecBackend()
        broker = ContainerExecBroker(backend, "cid-1")
        result = broker.dispatch(
            SandboxToolCall(kind="write", payload="x", path="a/b/c.py")
        )
        assert result.exit_code == 0
        assert any("/workspace/a/b/c.py" in c["command"] for c in backend.calls)

    def test_write_command_carries_realpath_guard(self) -> None:
        # The in-container guard catches symlink-parent escapes host code can't see.
        backend = FakeExecBackend()
        broker = ContainerExecBroker(backend, "cid-1")
        broker.dispatch(SandboxToolCall(kind="write", payload="x", path="ok.txt"))
        assert any("realpath -m" in c["command"] for c in backend.calls)
