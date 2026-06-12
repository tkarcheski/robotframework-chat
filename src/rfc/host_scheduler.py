"""Multi-host job scheduler with loaded-model affinity for Ollama test runs.

Implements the design approved in issue #306:

* A curated host inventory is loaded from ``host-config.toml``
  (:func:`load_host_config`).
* Work is a global queue of ``(model, suite)`` :class:`Job` items.
* :func:`run_jobs` dispatches jobs to a pool of host workers, preferring
  jobs whose model is already loaded on a host (per Ollama ``/api/ps``),
  falling back to any job whose model is available there.
* Concurrency is capped per host (``max_parallel``) and globally
  (``global_max_parallel``).

The scheduler is transport-agnostic: callers supply a ``run_fn(host, job)``
that performs the actual Robot Framework run and returns a result object.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONNECT_TIMEOUT = 2.0
DEFAULT_REQUEST_TIMEOUT = 5.0
DEFAULT_GLOBAL_MAX_PARALLEL = 4


# ---------------------------------------------------------------------------
# Host configuration (host-config.toml)
# ---------------------------------------------------------------------------


@dataclass
class HostSpec:
    """Static, user-curated description of one Ollama host."""

    name: str
    endpoint: str
    priority: int = 0
    max_parallel: int = 1
    skip_models: list[str] = field(default_factory=list)


@dataclass
class SchedulerDefaults:
    """Global knobs from the ``[defaults]`` table of host-config.toml."""

    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    global_max_parallel: int = DEFAULT_GLOBAL_MAX_PARALLEL


@dataclass
class HostConfig:
    """Parsed host-config.toml: curated hosts plus scheduler defaults."""

    hosts: list[HostSpec]
    defaults: SchedulerDefaults


def load_host_config(path: Path) -> HostConfig:
    """Load and validate a ``host-config.toml`` file.

    Args:
        path: Path to the TOML file (typically ``<repo>/host-config.toml``).

    Returns:
        Parsed :class:`HostConfig`.

    Raises:
        FileNotFoundError: If the file is missing — with a hint to copy
            ``host-config.toml.example``.
        ValueError: If no ``[[hosts]]`` entries are defined or a host is
            missing required fields.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Host config not found: {path}\n"
            f"Copy the committed example and edit it for your network:\n"
            f"  cp host-config.toml.example {path.name}"
        )

    data = tomllib.loads(path.read_text())

    hosts_raw = data.get("hosts") or []
    if not hosts_raw:
        raise ValueError(f"{path} defines no [[hosts]] entries")

    hosts: list[HostSpec] = []
    for entry in hosts_raw:
        endpoint = entry.get("endpoint")
        if not endpoint:
            raise ValueError(
                f"{path}: host entry {entry.get('name', '?')!r} is missing 'endpoint'"
            )
        hosts.append(
            HostSpec(
                name=str(entry.get("name") or endpoint),
                endpoint=str(endpoint).rstrip("/"),
                priority=int(entry.get("priority", 0)),
                max_parallel=int(entry.get("max_parallel", 1)),
                skip_models=[str(m) for m in entry.get("skip_models", [])],
            )
        )

    d = data.get("defaults") or {}
    defaults = SchedulerDefaults(
        connect_timeout=float(d.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT)),
        request_timeout=float(d.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)),
        global_max_parallel=int(
            d.get("global_max_parallel", DEFAULT_GLOBAL_MAX_PARALLEL)
        ),
    )

    return HostConfig(hosts=hosts, defaults=defaults)


# ---------------------------------------------------------------------------
# Scheduling primitives
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """One unit of work: run *suite* against *model* (host decided at dispatch)."""

    model: str
    suite: dict[str, Any]


@dataclass
class HostState:
    """Runtime view of a host: discovered models, load state, in-flight count."""

    spec: HostSpec
    models: list[str]
    loaded_models: list[str] = field(default_factory=list)
    last_loaded: str | None = None
    running: int = 0

    def eligible(self, job: Job) -> bool:
        """Whether this host can run *job* at all."""
        return job.model in self.models and job.model not in self.spec.skip_models

    def prefers(self, job: Job) -> bool:
        """Whether *job*'s model is (believed) resident in VRAM on this host.

        Once the scheduler has dispatched a model here, ``last_loaded``
        supersedes the ``/api/ps`` snapshot taken at discovery time.
        """
        if self.last_loaded is not None:
            return job.model == self.last_loaded
        return job.model in self.loaded_models


def pick_next_job(host: HostState, pending: list[Job]) -> int | None:
    """Choose the next job for *host* from the *pending* queue.

    Preference order:
      1. First job whose model is already loaded on this host (affinity).
      2. First job whose model is merely available on this host.

    Returns:
        Index into *pending*, or ``None`` if no pending job is eligible.
    """
    fallback: int | None = None
    for idx, job in enumerate(pending):
        if not host.eligible(job):
            continue
        if host.prefers(job):
            return idx
        if fallback is None:
            fallback = idx
    return fallback


@dataclass
class ScheduleOutcome:
    """What :func:`run_jobs` produced."""

    results: list[Any]
    unscheduled: list[Job]
    stopped_early: bool = False


def run_jobs(
    hosts: list[HostState],
    jobs: list[Job],
    run_fn: Callable[[HostState, Job], Any],
    *,
    global_max_parallel: int,
    stop_on_failure: bool = False,
    failure_of: Callable[[Any], bool] | None = None,
) -> ScheduleOutcome:
    """Dispatch *jobs* across *hosts* with affinity-aware scheduling.

    Args:
        hosts: Runtime host states (models + loaded models discovered upfront).
        jobs: Global ``(model, suite)`` queue.
        run_fn: Executes one job on one host; its return value is collected
            into :attr:`ScheduleOutcome.results`.
        global_max_parallel: Cap on simultaneously running jobs across hosts.
        stop_on_failure: If True, stop dispatching new jobs once *failure_of*
            flags a completed result (in-flight jobs are drained).
        failure_of: Predicate that decides whether a result is a failure.
            Defaults to checking a ``returncode`` attribute or key.

    Returns:
        :class:`ScheduleOutcome` with results, jobs that no host could take,
        and whether dispatch stopped early.
    """
    if failure_of is None:
        failure_of = _default_failure_of

    global_cap = max(1, global_max_parallel)
    pending = list(jobs)
    results: list[Any] = []
    in_flight: dict[Future[Any], HostState] = {}
    stopped_early = False
    # Higher priority hosts get first pick each dispatch round.
    hosts_by_priority = sorted(hosts, key=lambda h: -h.spec.priority)

    with ThreadPoolExecutor(max_workers=global_cap) as pool:
        while True:
            # Dispatch as much as caps and eligibility allow.
            if not stopped_early:
                dispatched = True
                while dispatched and pending and len(in_flight) < global_cap:
                    dispatched = False
                    for host in hosts_by_priority:
                        if len(in_flight) >= global_cap:
                            break
                        if host.running >= host.spec.max_parallel:
                            continue
                        idx = pick_next_job(host, pending)
                        if idx is None:
                            continue
                        job = pending.pop(idx)
                        host.running += 1
                        host.last_loaded = job.model
                        in_flight[pool.submit(run_fn, host, job)] = host
                        dispatched = True

            if not in_flight:
                break  # nothing running and nothing dispatchable

            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                host = in_flight.pop(future)
                host.running -= 1
                result = future.result()
                results.append(result)
                if stop_on_failure and failure_of(result):
                    stopped_early = True

    return ScheduleOutcome(
        results=results,
        unscheduled=pending if not stopped_early else [],
        stopped_early=stopped_early,
    )


def _default_failure_of(result: Any) -> bool:
    """Treat a non-zero ``returncode`` (attr or mapping key) as failure."""
    rc = getattr(result, "returncode", None)
    if rc is None and isinstance(result, dict):
        rc = result.get("returncode")
    return bool(rc)
