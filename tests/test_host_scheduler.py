"""Tests for rfc.host_scheduler — multi-host job scheduler with model affinity."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from rfc.host_scheduler import (
    HostSpec,
    HostState,
    Job,
    SchedulerDefaults,
    load_host_config,
    pick_next_job,
    run_jobs,
)

# ---------------------------------------------------------------------------
# load_host_config
# ---------------------------------------------------------------------------

_SAMPLE_TOML = """
[[hosts]]
name      = "workstation"
endpoint  = "http://192.168.1.10:11434"
priority  = 10
max_parallel = 1
skip_models  = []

[[hosts]]
name      = "gpu-rig"
endpoint  = "http://192.168.1.20:11434/"
priority  = 20
max_parallel = 2
skip_models  = ["llama3.3:70b"]

[defaults]
connect_timeout = 3
request_timeout = 7
global_max_parallel = 4
"""


class TestLoadHostConfig:
    def test_parses_hosts_and_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "host-config.toml"
        p.write_text(_SAMPLE_TOML)
        cfg = load_host_config(p)

        assert [h.name for h in cfg.hosts] == ["workstation", "gpu-rig"]
        ws, rig = cfg.hosts
        assert ws.endpoint == "http://192.168.1.10:11434"
        assert ws.priority == 10
        assert ws.max_parallel == 1
        assert ws.skip_models == []
        # Trailing slash stripped
        assert rig.endpoint == "http://192.168.1.20:11434"
        assert rig.priority == 20
        assert rig.max_parallel == 2
        assert rig.skip_models == ["llama3.3:70b"]

        assert cfg.defaults.connect_timeout == 3
        assert cfg.defaults.request_timeout == 7
        assert cfg.defaults.global_max_parallel == 4

    def test_missing_file_raises_with_copy_hint(self, tmp_path: Path) -> None:
        p = tmp_path / "host-config.toml"
        with pytest.raises(FileNotFoundError, match="host-config.toml.example"):
            load_host_config(p)

    def test_defaults_applied_when_omitted(self, tmp_path: Path) -> None:
        p = tmp_path / "host-config.toml"
        p.write_text(
            '[[hosts]]\nname = "h"\nendpoint = "http://h:11434"\n',
        )
        cfg = load_host_config(p)
        host = cfg.hosts[0]
        assert host.priority == 0
        assert host.max_parallel == 1
        assert host.skip_models == []
        assert cfg.defaults == SchedulerDefaults()

    def test_no_hosts_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "host-config.toml"
        p.write_text("[defaults]\nglobal_max_parallel = 2\n")
        with pytest.raises(ValueError, match=r"\[\[hosts\]\]"):
            load_host_config(p)

    def test_host_missing_endpoint_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "host-config.toml"
        p.write_text('[[hosts]]\nname = "h"\n')
        with pytest.raises(ValueError, match="endpoint"):
            load_host_config(p)


# ---------------------------------------------------------------------------
# HostSpec.skips_model — the single per-host skip predicate (#401)
# ---------------------------------------------------------------------------


class TestHostSpecSkipsModel:
    """The one home for the skip rule, shared by scheduler + RSI watcher (#401)."""

    def test_true_when_model_listed(self) -> None:
        spec = HostSpec(name="h", endpoint="http://h:11434", skip_models=["a", "b"])
        assert spec.skips_model("a") is True

    def test_false_when_model_absent(self) -> None:
        spec = HostSpec(name="h", endpoint="http://h:11434", skip_models=["a"])
        assert spec.skips_model("b") is False

    def test_false_when_skip_list_empty(self) -> None:
        spec = HostSpec(name="h", endpoint="http://h:11434")
        assert spec.skips_model("a") is False

    def test_host_state_eligible_routes_through_predicate(self) -> None:
        """HostState.eligible defers its skip clause to HostSpec.skips_model —
        the same predicate the watcher calls — so the two lanes share one rule
        and cannot re-drift (#401).

        Spied with ``autospec=True, side_effect=original`` (mirroring
        ``test_watch_skip_decision_routed_through_shared_predicate`` on the
        watcher lane) so the proof is non-vacuous: re-inlining the skip check
        to ``job.model not in self.spec.skip_models`` leaves the predicate
        uncalled and trips this test. Behaviour is preserved because
        ``side_effect`` delegates to the real method.
        """
        host = HostState(
            spec=HostSpec(name="h", endpoint="http://h:11434", skip_models=["a"]),
            models=["a", "b"],
        )
        original = HostSpec.skips_model
        with patch.object(
            HostSpec, "skips_model", autospec=True, side_effect=original
        ) as spy:
            assert host.eligible(Job(model="a", suite={})) is False  # skipped
            assert host.eligible(Job(model="b", suite={})) is True  # available
            # eligible still requires availability, independent of the skip
            # clause; an unavailable model short-circuits before the predicate.
            assert host.eligible(Job(model="c", suite={})) is False

        # Routing proof: the skip decision for every available model went
        # through the shared predicate. A re-inlined check would leave
        # call_args_list empty and fail here. "c" short-circuits on
        # availability, so the predicate is consulted only for "a" and "b".
        assert spy.call_args_list  # eligible actually routed through skips_model
        assert {call.args[1] for call in spy.call_args_list} == {"a", "b"}
        assert spy.call_args_list[0].args[1] == "a"  # skipped model tested first


# ---------------------------------------------------------------------------
# pick_next_job
# ---------------------------------------------------------------------------


def _host(
    name: str = "h1",
    *,
    models: list[str] | None = None,
    loaded: list[str] | None = None,
    skip: list[str] | None = None,
    priority: int = 0,
    max_parallel: int = 1,
) -> HostState:
    return HostState(
        spec=HostSpec(
            name=name,
            endpoint=f"http://{name}:11434",
            priority=priority,
            max_parallel=max_parallel,
            skip_models=skip or [],
        ),
        models=models or [],
        loaded_models=loaded or [],
    )


def _jobs(*models: str) -> list[Job]:
    return [
        Job(model=m, suite={"name": "math", "path": "robot/20__tier2/math/"})
        for m in models
    ]


class TestPickNextJob:
    def test_prefers_loaded_model(self) -> None:
        host = _host(models=["a", "b", "c"], loaded=["c"])
        jobs = _jobs("a", "b", "c")
        idx = pick_next_job(host, jobs)
        assert idx == 2  # "c" is loaded → preferred over earlier queue entries

    def test_prefers_last_loaded_over_ps_snapshot(self) -> None:
        host = _host(models=["a", "b", "c"], loaded=["c"])
        host.last_loaded = "b"
        jobs = _jobs("a", "b", "c")
        assert pick_next_job(host, jobs) == 1  # affinity follows last dispatched

    def test_falls_back_to_first_available(self) -> None:
        host = _host(models=["a", "b"], loaded=["zzz"])
        jobs = _jobs("a", "b")
        assert pick_next_job(host, jobs) == 0

    def test_skips_models_not_on_host(self) -> None:
        host = _host(models=["b"])
        jobs = _jobs("a", "b")
        assert pick_next_job(host, jobs) == 1

    def test_respects_skip_models(self) -> None:
        host = _host(models=["a", "b"], skip=["a"])
        jobs = _jobs("a", "b")
        assert pick_next_job(host, jobs) == 1

    def test_returns_none_when_nothing_eligible(self) -> None:
        host = _host(models=["a"], skip=["a"])
        jobs = _jobs("a")
        assert pick_next_job(host, jobs) is None


# ---------------------------------------------------------------------------
# run_jobs — the dispatcher
# ---------------------------------------------------------------------------


class TestRunJobs:
    def test_runs_every_schedulable_job_once(self) -> None:
        host = _host(models=["a", "b"])
        jobs = _jobs("a", "b")
        executed: list[tuple[str, str]] = []

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            executed.append((h.spec.name, j.model))
            return {"returncode": 0}

        outcome = run_jobs([host], jobs, run_fn, global_max_parallel=1)
        assert sorted(executed) == [("h1", "a"), ("h1", "b")]
        assert len(outcome.results) == 2
        assert outcome.unscheduled == []

    def test_affinity_ordering_loaded_model_runs_first(self) -> None:
        host = _host(models=["cold", "warm"], loaded=["warm"])
        jobs = _jobs("cold", "warm")
        executed: list[str] = []

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            executed.append(j.model)
            return {"returncode": 0}

        run_jobs([host], jobs, run_fn, global_max_parallel=1)
        assert executed == ["warm", "cold"]

    def test_skip_models_jobs_go_to_other_host(self) -> None:
        h1 = _host("h1", models=["big", "small"], skip=["big"])
        h2 = _host("h2", models=["big"])
        jobs = _jobs("big", "small")
        executed: list[tuple[str, str]] = []
        lock = threading.Lock()

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            with lock:
                executed.append((h.spec.name, j.model))
            return {"returncode": 0}

        outcome = run_jobs([h1, h2], jobs, run_fn, global_max_parallel=2)
        assert ("h2", "big") in executed
        assert ("h1", "small") in executed
        assert outcome.unscheduled == []

    def test_unschedulable_jobs_reported(self) -> None:
        host = _host(models=["a"], skip=["a"])
        jobs = _jobs("a")
        outcome = run_jobs(
            [host], jobs, lambda h, j: {"returncode": 0}, global_max_parallel=1
        )
        assert outcome.results == []
        assert [j.model for j in outcome.unscheduled] == ["a"]

    def test_higher_priority_host_picked_first(self) -> None:
        low = _host("low", models=["m"], priority=1)
        high = _host("high", models=["m"], priority=20)
        jobs = _jobs("m")
        executed: list[str] = []

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            executed.append(h.spec.name)
            return {"returncode": 0}

        run_jobs([low, high], jobs, run_fn, global_max_parallel=1)
        assert executed == ["high"]

    def test_per_host_max_parallel_cap(self) -> None:
        host = _host(models=["a", "b", "c", "d"], max_parallel=2)
        jobs = _jobs("a", "b", "c", "d")
        lock = threading.Lock()
        active = 0
        max_active = 0

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            threading.Event().wait(0.02)
            with lock:
                active -= 1
            return {"returncode": 0}

        outcome = run_jobs([host], jobs, run_fn, global_max_parallel=8)
        assert len(outcome.results) == 4
        assert max_active <= 2

    def test_hosts_run_in_parallel(self) -> None:
        """Two hosts must be able to run jobs simultaneously."""
        h1 = _host("h1", models=["a"])
        h2 = _host("h2", models=["b"])
        jobs = _jobs("a", "b")
        barrier = threading.Barrier(2, timeout=5)

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            barrier.wait()  # deadlocks (and times out) unless both run at once
            return {"returncode": 0}

        outcome = run_jobs([h1, h2], jobs, run_fn, global_max_parallel=4)
        assert len(outcome.results) == 2

    def test_global_max_parallel_cap(self) -> None:
        hosts = [_host(f"h{i}", models=["m"], max_parallel=4) for i in range(4)]
        # Make the same model available everywhere; 8 jobs of distinct models
        for h in hosts:
            h.models = [f"m{i}" for i in range(8)]
        jobs = _jobs(*[f"m{i}" for i in range(8)])
        lock = threading.Lock()
        active = 0
        max_active = 0

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            threading.Event().wait(0.02)
            with lock:
                active -= 1
            return {"returncode": 0}

        outcome = run_jobs(hosts, jobs, run_fn, global_max_parallel=3)
        assert len(outcome.results) == 8
        assert max_active <= 3

    def test_stop_on_failure_halts_dispatch(self) -> None:
        host = _host(models=["a", "b", "c"])
        jobs = _jobs("a", "b", "c")
        executed: list[str] = []

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            executed.append(j.model)
            return {"returncode": 1}

        outcome = run_jobs(
            [host],
            jobs,
            run_fn,
            global_max_parallel=1,
            stop_on_failure=True,
            failure_of=lambda r: r["returncode"] != 0,
        )
        assert len(executed) == 1
        assert len(outcome.results) == 1
        assert outcome.stopped_early

    def test_updates_last_loaded_for_affinity(self) -> None:
        """After dispatching model X, the host prefers further X jobs."""
        host = _host(models=["x", "y"])
        jobs = [
            Job(model="x", suite={"name": "s1", "path": "p1"}),
            Job(model="y", suite={"name": "s1", "path": "p1"}),
            Job(model="x", suite={"name": "s2", "path": "p2"}),
        ]
        executed: list[str] = []

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            executed.append(f"{j.model}/{j.suite['name']}")
            return {"returncode": 0}

        run_jobs([host], jobs, run_fn, global_max_parallel=1)
        # Both x jobs run back-to-back before y (affinity), regardless of queue order
        assert executed == ["x/s1", "x/s2", "y/s1"]


# ---------------------------------------------------------------------------
# Same-model serialization (#482)
# ---------------------------------------------------------------------------


class TestSameModelSerialization:
    """Two jobs targeting the same model must never overlap on one host.

    Residency in ``/api/ps`` does not mean idle (#482): if the scheduler
    dispatches two same-model suites to one host, both pass
    ``wait_until_ready`` and generate concurrently. The scheduler is the
    layer that must serialize them.
    """

    def test_same_model_jobs_never_overlap_on_one_host(self) -> None:
        host = _host(models=["a"], max_parallel=2)
        jobs = _jobs("a", "a", "a")
        lock = threading.Lock()
        active_a = 0
        max_active_a = 0

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            nonlocal active_a, max_active_a
            with lock:
                active_a += 1
                max_active_a = max(max_active_a, active_a)
            threading.Event().wait(0.02)
            with lock:
                active_a -= 1
            return {"returncode": 0}

        outcome = run_jobs([host], jobs, run_fn, global_max_parallel=8)
        assert len(outcome.results) == 3
        assert outcome.unscheduled == []
        assert max_active_a == 1

    def test_distinct_models_still_run_concurrently_on_one_host(self) -> None:
        host = _host(models=["a", "b"], max_parallel=2)
        jobs = _jobs("a", "b")
        barrier = threading.Barrier(2, timeout=5)

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            barrier.wait()  # deadlocks (and times out) unless both run at once
            return {"returncode": 0}

        outcome = run_jobs([host], jobs, run_fn, global_max_parallel=4)
        assert len(outcome.results) == 2

    def test_same_model_jobs_run_concurrently_on_distinct_hosts(self) -> None:
        h1 = _host("h1", models=["a"])
        h2 = _host("h2", models=["a"])
        jobs = _jobs("a", "a")
        barrier = threading.Barrier(2, timeout=5)

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            barrier.wait()
            return {"returncode": 0}

        outcome = run_jobs([h1, h2], jobs, run_fn, global_max_parallel=4)
        assert len(outcome.results) == 2

    def test_pick_next_job_skips_model_already_in_flight(self) -> None:
        host = _host(models=["a", "b"], max_parallel=2)
        host.active_models["a"] += 1
        jobs = _jobs("a", "b")
        idx = pick_next_job(host, jobs)
        assert idx is not None
        assert jobs[idx].model == "b"

    def test_pick_next_job_returns_none_when_only_busy_model_pending(self) -> None:
        host = _host(models=["a"], max_parallel=2)
        host.active_models["a"] += 1
        assert pick_next_job(host, _jobs("a", "a")) is None

    def test_bookkeeping_cleared_when_run_fn_raises(self) -> None:
        """A worker exception must not leave running/active_models counts
        stale on a reused HostState (Codex P2 on PR #519)."""
        host = _host(models=["a", "b"], max_parallel=2)
        release = threading.Event()

        def run_fn(h: HostState, j: Job) -> dict[str, Any]:
            if j.model == "a":
                raise RuntimeError("boom")
            release.wait(5)
            return {"returncode": 0}

        with pytest.raises(RuntimeError):
            try:
                run_jobs([host], _jobs("b", "a"), run_fn, global_max_parallel=4)
            finally:
                release.set()
        assert host.running == 0
        assert all(v == 0 for v in host.active_models.values())
