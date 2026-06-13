#!/usr/bin/env python3
"""Discover local Ollama nodes and run test suites against every model.

Two modes (issue #306):

* ``--mode toml`` (default; ``make run-local-models``) — reads a curated
  host inventory from ``host-config.toml`` at the repo root. Jobs are
  scheduled across hosts in parallel, preferring models already loaded
  in VRAM (per ``/api/ps``).
* ``--mode external`` (``make run-all-external``) — legacy wide-net
  discovery via ``OLLAMA_NODES_LIST`` / ``OLLAMA_ENDPOINT`` / subnet
  scan; runs everything it finds through the same scheduler, with
  ``execution.parallel`` from ``config/local_models.yaml`` as the
  global concurrency cap (default 1 — sequential, like before).

Usage::

    # Run against curated hosts (host-config.toml required)
    python scripts/run_local_models.py

    # Legacy wide-net discovery
    python scripts/run_local_models.py --mode external

    # Discover nodes only (no model query, no test execution)
    python scripts/run_local_models.py --discover-nodes --mode external

    # Dry-run — show what would be executed without running
    python scripts/run_local_models.py --dry-run

Environment variables (external mode):
    OLLAMA_ENDPOINT   -- starting-point endpoint (default http://localhost:11434)
    DEFAULT_MODEL     -- fallback model name
    OLLAMA_NODES_LIST -- comma-separated hostnames to probe
    OLLAMA_SUBNET     -- CIDR to scan (e.g. 192.168.1.0/24)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml

# ---------------------------------------------------------------------------
# Project root and sibling imports
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from rfc.host_scheduler import (  # noqa: E402
    HostConfig,
    HostSpec,
    HostState,
    Job,
    load_host_config,
    run_jobs,
)
from rfc.providers import (  # noqa: E402
    ProviderConfig,
    discover_free_models,
    load_providers,
    resolve_api_key,
    select_models_within_budget,
)
from scripts.discover_ollama import (  # noqa: E402
    _probe_port,
    _query_loaded_models,
    _query_models,
)

DEFAULT_CONFIG = _project_root / "config" / "local_models.yaml"
TEST_SUITES_CONFIG = _project_root / "config" / "test_suites.yaml"
HOST_CONFIG_PATH = _project_root / "host-config.toml"

# Pseudo-suite name recorded when a model fails its preflight probe and its
# real suites are skipped (issue #426).
PREFLIGHT_SUITE = "<preflight>"

# Default ceiling for one preflight generate call. Cold-loading a large model
# can take tens of minutes (observed ~26 min for glm-4.7-flash:q8_0), so this
# must be generous; override with execution.preflight_timeout.
DEFAULT_PREFLIGHT_TIMEOUT = 1800


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Outcome of a single (node, model, suite) Robot Framework run."""

    node: str
    model: str
    suite: str
    returncode: int
    output_dir: str


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_local_config(path: Path | None = None) -> dict[str, Any]:
    """Load the local-models YAML config.

    Args:
        path: Explicit path to the YAML file.  Falls back to
              ``config/local_models.yaml`` relative to the project root.

    Returns:
        Parsed YAML as a dict.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    p = path or DEFAULT_CONFIG
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    with open(p) as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_name(name: str) -> str:
    """Replace characters unsafe for filesystem paths.

    Keeps alphanumerics, hyphens, underscores, and dots.
    Colons (common in Ollama model tags) become underscores.
    """
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def _load_node_list() -> list[dict[str, Any]]:
    """Load nodes from env-var or config/test_suites.yaml."""
    env_val = os.environ.get("OLLAMA_NODES_LIST", "").strip()
    if env_val:
        nodes: list[dict[str, Any]] = []
        for entry in env_val.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                host, port_s = entry.rsplit(":", 1)
                nodes.append({"hostname": host, "port": int(port_s)})
            else:
                nodes.append({"hostname": entry, "port": 11434})
        return nodes

    # Fall back to the starting-point endpoint
    endpoint = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
    # Parse host:port from the URL
    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    return [{"hostname": host, "port": port}]


def _nodes_from_host_config(host_config: HostConfig) -> list[dict[str, Any]]:
    """Convert curated host-config.toml entries into probe-able node dicts.

    The scheduler fields (``name``, ``priority``, ``max_parallel``,
    ``skip_models``) are carried through discovery untouched.
    """
    nodes: list[dict[str, Any]] = []
    for spec in host_config.hosts:
        parsed = urlparse(spec.endpoint)
        nodes.append(
            {
                "hostname": parsed.hostname or spec.name,
                "port": parsed.port or 11434,
                "name": spec.name,
                "priority": spec.priority,
                "max_parallel": spec.max_parallel,
                "skip_models": list(spec.skip_models),
            }
        )
    return nodes


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_local_models(
    nodes: list[dict[str, Any]],
    connect_timeout: float = 2,
    max_workers: int = 64,
) -> list[dict[str, Any]]:
    """Probe nodes and return those that are online with their models.

    Args:
        nodes: List of ``{"hostname": ..., "port": ...}`` dicts.
        connect_timeout: TCP probe timeout in seconds.
        max_workers: Max parallel workers.

    Returns:
        List of dicts with ``hostname``, ``endpoint``, ``models``, and
        ``loaded_models`` (per Ollama ``/api/ps``) keys. Scheduler fields
        present on the input node (``name``, ``priority``, ``max_parallel``,
        ``skip_models``) are carried through. Only online nodes are included.
    """
    if not nodes:
        return []

    results: list[dict[str, Any]] = []

    def _probe(node: dict[str, Any]) -> dict[str, Any] | None:
        hostname = node["hostname"]
        port = node.get("port", 11434)
        endpoint = f"http://{hostname}:{port}"
        online = _probe_port(hostname, port, timeout=connect_timeout)
        if not online:
            return None
        models = _query_models(endpoint)
        result = {
            "hostname": hostname,
            "endpoint": endpoint,
            "models": models,
            "loaded_models": _query_loaded_models(endpoint),
        }
        for key in ("name", "priority", "max_parallel", "skip_models"):
            if key in node:
                result[key] = node[key]
        return result

    with ThreadPoolExecutor(max_workers=min(len(nodes), max_workers)) as pool:
        futures = {pool.submit(_probe, n): n for n in nodes}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    return sorted(results, key=lambda r: r["hostname"])


# ---------------------------------------------------------------------------
# Robot command builder
# ---------------------------------------------------------------------------


def _build_robot_command(
    *,
    config: dict[str, Any],
    suite: dict[str, Any],
    endpoint: str,
    model: str,
    node_name: str,
) -> list[str]:
    """Build a ``uv run robot`` command for a single (node, model, suite) run.

    Returns:
        List of command-line tokens.
    """
    execution = config.get("execution", {})
    output_template = execution.get("output_dir", "results/local/{node}/{model}")
    output_dir = output_template.format(
        node=_sanitize_name(node_name),
        model=_sanitize_name(model),
    )

    cmd: list[str] = ["uv", "run", "robot"]

    # Output directory
    cmd.extend(["-d", output_dir])

    # Listeners
    for listener in execution.get("listeners", []):
        cmd.extend(["--listener", listener])

    # Variable overrides — Robot Framework syntax is NAME:VALUE
    cmd.extend(["--variable", f"OLLAMA_ENDPOINT:{endpoint}"])
    cmd.extend(["--variable", f"DEFAULT_MODEL:{model}"])

    # Extra args from config
    cmd.extend(execution.get("extra_args", []))

    # Suite path
    cmd.append(suite["path"])

    return cmd


# ---------------------------------------------------------------------------
# Preflight probe (issue #426)
# ---------------------------------------------------------------------------


def preflight_model(
    endpoint: str,
    model: str,
    *,
    timeout: float = DEFAULT_PREFLIGHT_TIMEOUT,
) -> tuple[bool, str]:
    """Probe a model with one tiny prompt before running its suites.

    A model that errors, times out, or returns an empty response (the
    glm-4.7-flash:q8_0 symptom from issue #426) would otherwise fail every
    test of every suite — each with its own retries and long waits — before
    the runner moves on. One probe up front lets the runner record the
    failure and skip straight to the next model.

    Args:
        endpoint: Ollama base URL (e.g. ``http://host:11434``).
        model: Model name to probe.
        timeout: Max seconds for the probe request (cold model loads can
            take tens of minutes, so the default is generous).

    Returns:
        ``(ok, reason)`` — ``reason`` is ``"ok"`` on success, otherwise a
        short human-readable failure description.
    """
    try:
        resp = requests.post(
            f"{endpoint}/api/generate",
            json={
                "model": model,
                "prompt": "Reply with the single word: ok",
                "stream": False,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        text = (resp.json().get("response") or "").strip()
    except requests.RequestException as e:
        return False, f"request failed: {e}"
    except ValueError as e:
        return False, f"invalid JSON response: {e}"

    if not text:
        return False, "empty response from model"
    return True, "ok"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _host_states_from_nodes(
    nodes_with_models: list[dict[str, Any]],
) -> list[HostState]:
    """Build scheduler host states from discovery output."""
    states: list[HostState] = []
    for node in nodes_with_models:
        spec = HostSpec(
            name=str(node.get("name", node["hostname"])),
            endpoint=node["endpoint"],
            priority=int(node.get("priority", 0)),
            max_parallel=int(node.get("max_parallel", 1)),
            skip_models=list(node.get("skip_models", [])),
        )
        states.append(
            HostState(
                spec=spec,
                models=list(node.get("models", [])),
                loaded_models=list(node.get("loaded_models", [])),
            )
        )
    return states


def _build_jobs(
    config: dict[str, Any],
    nodes_with_models: list[dict[str, Any]],
) -> list[Job]:
    """Build the global ``(model, suite)`` job queue.

    Models are deduplicated across hosts (a model present on several hosts
    runs once per suite, on whichever host claims it first). Jobs are
    model-major so a host that claims a model tends to keep it loaded for
    all its suites.
    """
    suites = config.get("test_suites", [])
    seen: set[str] = set()
    ordered_models: list[str] = []
    for node in nodes_with_models:
        for model in node.get("models", []):
            if model not in seen:
                seen.add(model)
                ordered_models.append(model)

    return [Job(model=m, suite=s) for m in ordered_models for s in suites]


def run_model_suites(
    config: dict[str, Any],
    nodes_with_models: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    global_max_parallel: int = 1,
) -> list[RunResult]:
    """Run configured test suites against every discovered model.

    Jobs form a global ``(model, suite)`` queue dispatched across hosts by
    :func:`rfc.host_scheduler.run_jobs`: each host prefers jobs whose model
    is already loaded (per ``/api/ps``), honors ``skip_models``, and runs at
    most ``max_parallel`` jobs concurrently.

    Args:
        config: Parsed local_models.yaml.
        nodes_with_models: Output of :func:`discover_local_models`.
        dry_run: If True, print commands without executing (sequential).
        global_max_parallel: Cap on concurrent runs across all hosts.

    Returns:
        List of :class:`RunResult` objects.
    """
    execution = config.get("execution", {})
    continue_on_failure = execution.get("continue_on_failure", True)
    preflight_enabled = execution.get("preflight", False)
    preflight_timeout = execution.get("preflight_timeout", DEFAULT_PREFLIGHT_TIMEOUT)

    hosts = _host_states_from_nodes(nodes_with_models)
    jobs = _build_jobs(config, nodes_with_models)
    print_lock = threading.Lock()

    def _run(host: HostState, job: Job) -> RunResult:
        node_name = host.spec.name
        endpoint = host.spec.endpoint

        if preflight_enabled and not dry_run:
            ok, reason = preflight_model(endpoint, job.model, timeout=preflight_timeout)
            if not ok:
                with print_lock:
                    print(
                        f"\n  [preflight] SKIPPING {job.model}@{node_name}: "
                        f"{reason}\n"
                        f"  [preflight] Recording failure and continuing with "
                        f"the next model."
                    )
                return RunResult(
                    node=node_name,
                    model=job.model,
                    suite=PREFLIGHT_SUITE,
                    returncode=1,
                    output_dir="",
                )

        cmd = _build_robot_command(
            config=config,
            suite=job.suite,
            endpoint=endpoint,
            model=job.model,
            node_name=node_name,
        )
        output_dir = execution.get("output_dir", "results/local/{node}/{model}").format(
            node=_sanitize_name(node_name),
            model=_sanitize_name(job.model),
        )

        if dry_run:
            with print_lock:
                print(f"[DRY-RUN] {' '.join(cmd)}")
            return RunResult(
                node=node_name,
                model=job.model,
                suite=job.suite["name"],
                returncode=0,
                output_dir=output_dir,
            )

        with print_lock:
            print(
                f"\n{'=' * 70}\n"
                f"  Node:  {node_name}\n"
                f"  Model: {job.model}\n"
                f"  Suite: {job.suite['name']}\n"
                f"{'=' * 70}\n"
            )
            print(f"  > {' '.join(cmd)}\n")

        env = {
            **os.environ,
            "DEFAULT_MODEL": job.model,
            "OLLAMA_ENDPOINT": endpoint,
        }
        proc = subprocess.run(cmd, cwd=str(_project_root), env=env)

        return RunResult(
            node=node_name,
            model=job.model,
            suite=job.suite["name"],
            returncode=proc.returncode,
            output_dir=output_dir,
        )

    outcome = run_jobs(
        hosts,
        jobs,
        _run,
        # Dry runs stay sequential so output is deterministic and readable.
        global_max_parallel=1 if dry_run else global_max_parallel,
        stop_on_failure=not continue_on_failure,
    )

    if outcome.stopped_early:
        failed = [r for r in outcome.results if r.returncode != 0]
        if failed:
            r = failed[0]
            print(
                f"\nSuite '{r.suite}' failed for {r.model}@{r.node} "
                f"(rc={r.returncode}). Stopping (continue_on_failure=false)."
            )

    if outcome.unscheduled:
        print("\n  WARNING: jobs no host could run (check skip_models):")
        for job in outcome.unscheduled:
            print(f"    - {job.suite['name']} | {job.model}")

    return outcome.results


# ---------------------------------------------------------------------------
# External providers (issue #507)
# ---------------------------------------------------------------------------


def _build_provider_robot_command(
    *,
    config: dict[str, Any],
    suite: dict[str, Any],
    provider: ProviderConfig,
    model: str,
) -> list[str]:
    """Build a ``uv run robot`` command for one (provider, model, suite) run.

    Unlike :func:`_build_robot_command` there is no ``OLLAMA_ENDPOINT``
    override — provider runs select the OpenAI-compatible backend through
    subprocess env vars (``LLM_PROVIDER=openai`` etc., see
    :func:`run_provider_suites`). ``DEFAULT_MODEL`` carries the raw model id
    because that is what the API expects verbatim.
    """
    execution = config.get("execution", {})
    output_template = execution.get("output_dir", "results/local/{node}/{model}")
    output_dir = output_template.format(
        node=_sanitize_name(provider.name),
        model=_sanitize_name(model),
    )

    cmd: list[str] = ["uv", "run", "robot", "-d", output_dir]
    for listener in execution.get("listeners", []):
        cmd.extend(["--listener", listener])
    cmd.extend(["--variable", f"DEFAULT_MODEL:{model}"])
    cmd.extend(execution.get("extra_args", []))
    cmd.append(suite["path"])
    return cmd


def run_provider_suites(
    config: dict[str, Any],
    provider: ProviderConfig,
    api_key: str,
    models: list[str],
    *,
    dry_run: bool = False,
    sleep_fn: Any = time.sleep,
) -> list[RunResult]:
    """Run every configured suite against each provider model, sequentially.

    Jobs are model-major and strictly sequential — remote providers have no
    VRAM locality to exploit, and sequencing makes the rate budget
    enforceable: consecutive job starts are spaced at least
    ``requests_per_suite_estimate / requests_per_minute`` minutes apart so a
    suite's burst of LLM calls stays within the provider's RPM limit
    (OpenRouter free pool: 20 RPM).

    Args:
        config: Parsed local_models.yaml.
        provider: The provider to run against.
        api_key: Resolved API key (callers skip the provider when absent).
        models: Raw model ids to run (already budget-filtered).
        dry_run: Print commands without executing.
        sleep_fn: Injectable sleep for the RPM pacing (tests).

    Returns:
        List of :class:`RunResult`, with ``model`` recorded as
        ``<provider>/<model-id>`` for attribution.
    """
    execution = config.get("execution", {})
    suites = config.get("test_suites", [])
    tag = f"[provider:{provider.name}]"

    pacing_gap = 0.0
    if provider.requests_per_minute > 0:
        pacing_gap = provider.requests_per_suite_estimate * (
            60.0 / provider.requests_per_minute
        )

    results: list[RunResult] = []
    prev_start: float | None = None
    for model in models:
        watermark = f"{provider.name}/{model}"
        for suite in suites:
            needed = int(suite.get("min_context_tokens", 0))
            if 0 < provider.max_context_tokens < needed:
                print(
                    f"  {tag} skipping suite '{suite['name']}': needs "
                    f"{needed} context tokens, provider caps at "
                    f"{provider.max_context_tokens}"
                )
                continue
            cmd = _build_provider_robot_command(
                config=config, suite=suite, provider=provider, model=model
            )
            output_dir = execution.get(
                "output_dir", "results/local/{node}/{model}"
            ).format(
                node=_sanitize_name(provider.name),
                model=_sanitize_name(model),
            )

            if dry_run:
                print(f"[DRY-RUN] {' '.join(cmd)}")
                results.append(
                    RunResult(
                        node=provider.name,
                        model=watermark,
                        suite=suite["name"],
                        returncode=0,
                        output_dir=output_dir,
                    )
                )
                continue

            if prev_start is not None and pacing_gap > 0:
                remaining = pacing_gap - (time.monotonic() - prev_start)
                if remaining > 0:
                    print(
                        f"  {tag} pacing for rate budget "
                        f"({provider.requests_per_minute} RPM): "
                        f"sleeping {remaining:.0f}s"
                    )
                    sleep_fn(remaining)
            prev_start = time.monotonic()

            print(
                f"\n{'=' * 70}\n"
                f"  Provider: {provider.name}\n"
                f"  Model:    {watermark}\n"
                f"  Suite:    {suite['name']}\n"
                f"{'=' * 70}\n"
            )
            print(f"  > {' '.join(cmd)}\n")

            env = {
                **os.environ,
                "LLM_PROVIDER": "openai",
                "OPENAI_BASE_URL": provider.base_url,
                "OPENAI_API_KEY": api_key,
                # Raw id for the API; prefixed watermark for attribution.
                "DEFAULT_MODEL": model,
                "RFC_MODEL_NAME": watermark,
            }
            proc = subprocess.run(cmd, cwd=str(_project_root), env=env)
            results.append(
                RunResult(
                    node=provider.name,
                    model=watermark,
                    suite=suite["name"],
                    returncode=proc.returncode,
                    output_dir=output_dir,
                )
            )

    return results


def run_provider_runs(
    config: dict[str, Any],
    *,
    dry_run: bool = False,
) -> list[RunResult]:
    """Run all configured external providers (issue #507).

    Per provider: resolve the API key (absent → skip-and-log, so the whole
    feature is inert without credentials), optionally discover the free-pool
    model list, apply the daily request budget, and run the suites.

    Returns:
        Combined :class:`RunResult` list across providers (empty when no
        provider is configured or runnable).
    """
    providers = load_providers(config)
    if not providers:
        return []

    suites = config.get("test_suites", [])
    results: list[RunResult] = []
    for provider in providers:
        tag = f"[provider:{provider.name}]"

        api_key = resolve_api_key(provider)
        if api_key is None:
            print(
                f"{tag} {provider.api_key_env} not set — "
                f"skipping provider (skip-and-log)."
            )
            continue

        models = list(provider.models)
        if provider.discover_free_pool:
            try:
                free = discover_free_models(provider.base_url, api_key)
            except Exception as e:  # noqa: BLE001 - discovery is optional
                print(f"{tag} free-pool discovery failed: {e} (skip-and-log)")
                free = []
            seen = set(models)
            models.extend(m for m in free if m not in seen)

        if not models:
            print(f"{tag} no models to run — skipping provider.")
            continue

        kept = select_models_within_budget(
            models,
            len(suites),
            max_requests_per_day=provider.max_requests_per_day,
            requests_per_suite_estimate=provider.requests_per_suite_estimate,
        )
        if len(kept) < len(models):
            print(
                f"{tag} daily budget ({provider.max_requests_per_day} requests): "
                f"running {len(kept)} of {len(models)} model(s)."
            )
        if not kept:
            print(f"{tag} budget allows no runs — skipping provider.")
            continue

        print(
            f"{tag} running {len(suites)} suite(s) x {len(kept)} model(s) "
            f"via {provider.base_url}"
        )
        results.extend(
            run_provider_suites(config, provider, api_key, kept, dry_run=dry_run)
        )

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _print_summary(results: list[RunResult]) -> None:
    """Print a human-readable summary of all runs."""
    if not results:
        print("\nNo test runs were executed.")
        return

    skipped = [r for r in results if r.suite == PREFLIGHT_SUITE]
    passed = [r for r in results if r.returncode == 0 and r.suite != PREFLIGHT_SUITE]
    failed = [r for r in results if r.returncode != 0 and r.suite != PREFLIGHT_SUITE]

    print(f"\n{'=' * 70}")
    print("  Run Summary")
    print(f"{'=' * 70}")
    print(f"  Total runs: {len(results)}")
    print(f"  Passed:     {len(passed)}")
    print(f"  Failed:     {len(failed)}")
    if skipped:
        print(f"  Skipped:    {len(skipped)} model(s) failed preflight")

    if failed:
        print("\n  Failed runs:")
        for r in failed:
            print(f"    - {r.suite} | {r.model}@{r.node} (rc={r.returncode})")

    if skipped:
        print("\n  Models skipped (preflight failed):")
        for r in skipped:
            print(f"    - {r.model}@{r.node}")

    print()


# ---------------------------------------------------------------------------
# ANSI helpers (mirroring diagnose_superset_db.py)
# ---------------------------------------------------------------------------

_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _db_ok(msg: str) -> None:
    print(f"  {_GREEN}OK{_RESET}  {msg}")


def _db_fail(msg: str) -> None:
    print(f"  {_RED}FAIL{_RESET}  {msg}")


def _db_warn(msg: str) -> None:
    print(f"  {_YELLOW}WARN{_RESET}  {msg}")


def _db_heading(msg: str) -> None:
    print(f"\n{_BOLD}── {msg} ──{_RESET}")


# ---------------------------------------------------------------------------
# Post-run database verification
# ---------------------------------------------------------------------------


def verify_db_results(
    results: list[RunResult],
    *,
    dry_run: bool = False,
) -> bool:
    """Check that test runs were recorded in the database.

    Returns True if verification passed or was skipped, False on failure.
    """
    if dry_run:
        return True

    if not results:
        return True

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        _db_heading("Database Verification")
        _db_warn(
            "DATABASE_URL not set — skipping DB verification.\n"
            "        → Results may have been written to local SQLite instead.\n"
            "        → Set DATABASE_URL in .env for PostgreSQL archival."
        )
        return True

    _db_heading("Database Verification")
    expected_count = len(results)

    try:
        from rfc.test_database import TestDatabase

        db = TestDatabase(database_url=database_url)
    except Exception as e:
        _db_fail(
            f"Cannot connect to database: {e}\n"
            "        → Check DATABASE_URL and database connectivity.\n"
            "        → Run: make superset-diagnose"
        )
        return False

    try:
        recent_runs = db.get_recent_runs(limit=expected_count * 2)
    except Exception as e:
        _db_fail(f"Failed to query recent runs: {e}")
        return False

    # Count runs within the last 30 minutes.
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=30)
    recent_count = 0
    for run in recent_runs:
        ts = run.get("timestamp", "")
        if isinstance(ts, str):
            try:
                run_time = datetime.fromisoformat(ts)
                if run_time.tzinfo is None:
                    run_time = run_time.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        elif isinstance(ts, datetime):
            run_time = ts
            if run_time.tzinfo is None:
                run_time = run_time.replace(tzinfo=timezone.utc)
        else:
            continue

        if run_time >= cutoff:
            recent_count += 1

    if recent_count >= expected_count:
        _db_ok(
            f"Found {recent_count} recent test run(s) in database "
            f"(expected {expected_count})"
        )
        return True
    elif recent_count > 0:
        _db_warn(
            f"Found {recent_count} of {expected_count} expected test run(s) "
            f"in database (partial archival).\n"
            "        → Some runs may not have been archived.\n"
            "        → Check Robot output for 'DbListener: FAILED to archive results'."
        )
        return True
    else:
        _db_fail(
            f"Found 0 of {expected_count} expected test run(s) in database.\n"
            "        → Data pipeline failure: no results were archived.\n"
            "        → Check DATABASE_URL is correct.\n"
            "        → Check Robot output for DbListener errors.\n"
            "        → Run: make superset-diagnose"
        )
        return False


def _maybe_audit(*, dry_run: bool, audit: bool) -> None:
    """Generate (and commit) the coverage report after the first executed pass.

    Runs once per invocation — the first full pass is what establishes whether
    every model has been measured against every suite, which is the coverage
    question the report answers. Later iterations in a forever run only add
    repeat data, so re-auditing each pass would just churn the report and the
    git history.

    The audit is a post-processing convenience, never a gate: a multi-hour test
    run must not die because the report failed to render or commit. So any error
    here is logged and swallowed, mirroring CLAUDE.md's skip-and-log rule for
    optional steps.
    """
    if dry_run or not audit:
        return
    try:
        from scripts.audit_robot_reports import (
            DEFAULT_AUDIT_DIR,
            DEFAULT_RESULTS_ROOT,
            run_audit,
        )

        print(f"\n{'#' * 70}\n  Coverage audit (first executed pass)\n{'#' * 70}\n")
        run_audit(
            results_root=DEFAULT_RESULTS_ROOT,
            version=None,
            audit_dir=DEFAULT_AUDIT_DIR,
            commit=True,
        )
    except Exception as e:  # noqa: BLE001 - audit must never abort the run
        print(f"  [audit] skipped due to error: {e}")


def run_iteration_loop(
    config: dict[str, Any],
    *,
    iterations: int = 1,
    dry_run: bool = False,
    audit: bool = True,
    mode: str = "external",
    host_config: HostConfig | None = None,
) -> bool:
    """Run the full discover → test → summary cycle, optionally repeating.

    Args:
        config: Parsed local_models.yaml.
        iterations: How many passes to run.
            *  1  (default) — run once (backward compatible).
            * >1  — run exactly *iterations* passes.
            *  0  — run until a test failure occurs ("stop-on-error").
            * -1  — run forever (until ``KeyboardInterrupt``).
        dry_run: If True, print commands without executing.
        audit: If True (default), generate + commit the coverage report after
            the first pass that runs tests. See :func:`_maybe_audit`.
        mode: ``"toml"`` (curated host-config.toml hosts) or ``"external"``
            (legacy env-var / subnet discovery).
        host_config: Parsed host-config.toml; required when ``mode="toml"``.

    Returns:
        True if any pass had a test failure, False otherwise.
    """
    discovery_cfg = config.get("discovery", {})
    execution = config.get("execution", {})
    had_failure = False
    iteration = 0
    audited = False

    if mode == "toml":
        if host_config is None:
            raise ValueError("mode='toml' requires a parsed host_config")
        connect_timeout = host_config.defaults.connect_timeout
        global_max_parallel = host_config.defaults.global_max_parallel
        if "parallel" in execution:
            print(
                "WARNING: execution.parallel in config/local_models.yaml is "
                "deprecated for `make run-local-models` — use "
                "global_max_parallel in host-config.toml instead "
                "(execution.parallel still applies to `make run-all-external`)."
            )
    else:
        connect_timeout = discovery_cfg.get("connect_timeout", 2)
        global_max_parallel = int(execution.get("parallel", 1))

    try:
        while True:
            iteration += 1

            # Check termination for finite iterations (> 0)
            if iterations > 0 and iteration > iterations:
                break

            # Iteration header
            if iterations <= 0:
                label = f"Iteration {iteration}"
            else:
                label = f"Iteration {iteration}/{iterations}"
            print(f"\n{'#' * 70}")
            print(f"  {label}")
            print(f"{'#' * 70}\n")

            # Re-discover each iteration (nodes may come/go)
            if mode == "toml" and host_config is not None:
                node_list = _nodes_from_host_config(host_config)
            else:
                node_list = _load_node_list()
            print(f"Probing {len(node_list)} node(s)...")

            nodes_with_models = discover_local_models(
                node_list,
                connect_timeout=connect_timeout,
                max_workers=discovery_cfg.get("max_workers", 64),
            )

            _print_discovered_nodes(nodes_with_models)

            suites = config.get("test_suites", [])
            distinct_models = {m for n in nodes_with_models for m in n["models"]}
            total_models = len(distinct_models)
            total_runs = total_models * len(suites)

            results: list[RunResult] = []
            if total_runs == 0:
                print("No local models discovered.")
            else:
                print(
                    f"Running {len(suites)} suite(s) x {total_models} model(s) = "
                    f"{total_runs} total run(s) "
                    f"(global_max_parallel={global_max_parallel})\n"
                )
                results = run_model_suites(
                    config,
                    nodes_with_models,
                    dry_run=dry_run,
                    global_max_parallel=global_max_parallel,
                )

            # External providers run regardless of local discovery (#507):
            # a host with zero Ollama nodes can still sweep OpenRouter.
            results = results + run_provider_runs(config, dry_run=dry_run)

            if not results:
                print("No models discovered — nothing to run.")
                # For infinite/stop-on-error, keep trying
                continue

            _print_summary(results)

            # Verify data landed in the database.
            if not dry_run:
                db_ok = verify_db_results(results)
                if not db_ok:
                    had_failure = True

            pass_had_failure = any(r.returncode != 0 for r in results)
            if pass_had_failure:
                had_failure = True

            # Audit coverage once, after the first pass that actually ran tests.
            # Gating on iteration == 1 would skip the audit entirely whenever the
            # early iterations discover no models and `continue` before this point.
            if not audited:
                _maybe_audit(dry_run=dry_run, audit=audit)
                audited = True

            # iterations=0: stop on first failure
            if iterations == 0 and pass_had_failure:
                print("Stopping — failure detected (iterations=0, stop-on-error).")
                break

    except KeyboardInterrupt:
        print(f"\n\nInterrupted after {iteration} iteration(s).")

    return had_failure


def _print_discovered_nodes(nodes_with_models: list[dict[str, Any]]) -> None:
    """Print discovered nodes and their models."""
    if not nodes_with_models:
        print("No Ollama nodes found on the network.")
        return

    total_models = sum(len(n["models"]) for n in nodes_with_models)
    print(
        f"\nDiscovered {len(nodes_with_models)} node(s) with {total_models} model(s):\n"
    )

    for node in nodes_with_models:
        model_count = len(node["models"])
        print(
            f"  {node['hostname']:20s}  {node['endpoint']:30s}  {model_count} model(s)"
        )
        loaded = set(node.get("loaded_models", []))
        for m in node["models"]:
            marker = "  [loaded]" if m in loaded else ""
            print(f"    - {m}{marker}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover local Ollama nodes and run test suites against every model"
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Path to local_models.yaml (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--discover-nodes",
        action="store_true",
        help="Discover nodes only (no model query, no test execution)",
    )
    parser.add_argument(
        "--discover-models",
        action="store_true",
        help="Discover nodes and models (no test execution)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running tests",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        metavar="N",
        help=(
            "How many full discover+test cycles to run. "
            "1 = once (default), N>1 = exactly N times, "
            "-1 = forever (until Ctrl+C), "
            "0 = repeat until a test failure (stop-on-error)"
        ),
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Skip the coverage audit + commit after the first executed pass",
    )
    parser.add_argument(
        "--mode",
        choices=("toml", "external"),
        default="toml",
        help=(
            "Host source: 'toml' reads curated hosts from host-config.toml "
            "(default; `make run-local-models`), 'external' uses legacy "
            "env-var/subnet discovery (`make run-all-external`)"
        ),
    )
    parser.add_argument(
        "--host-config",
        default=str(HOST_CONFIG_PATH),
        help=f"Path to host-config.toml (default: {HOST_CONFIG_PATH})",
    )
    args = parser.parse_args()

    config = load_local_config(Path(args.config))
    discovery_cfg = config.get("discovery", {})

    host_config: HostConfig | None = None
    if args.mode == "toml":
        try:
            host_config = load_host_config(Path(args.host_config))
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)

    def _node_list() -> list[dict[str, Any]]:
        if host_config is not None:
            return _nodes_from_host_config(host_config)
        return _load_node_list()

    connect_timeout = (
        host_config.defaults.connect_timeout
        if host_config is not None
        else discovery_cfg.get("connect_timeout", 2)
    )

    if args.discover_nodes:
        node_list = _node_list()
        print(f"Probing {len(node_list)} node(s)...")
        for node in node_list:
            hostname = node["hostname"]
            port = node.get("port", 11434)
            online = _probe_port(hostname, port, timeout=connect_timeout)
            status = "ONLINE" if online else "OFFLINE"
            print(f"  {hostname}:{port}  {status}")
        return

    if args.discover_models:
        node_list = _node_list()
        print(f"Probing {len(node_list)} node(s)...")
        nodes_with_models = discover_local_models(
            node_list,
            connect_timeout=connect_timeout,
            max_workers=discovery_cfg.get("max_workers", 64),
        )
        _print_discovered_nodes(nodes_with_models)
        return

    # Run the iteration loop
    had_failure = run_iteration_loop(
        config,
        iterations=args.iterations,
        dry_run=args.dry_run,
        audit=not args.no_audit,
        mode=args.mode,
        host_config=host_config,
    )

    if had_failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
