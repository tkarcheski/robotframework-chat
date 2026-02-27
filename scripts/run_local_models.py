#!/usr/bin/env python3
"""Discover local Ollama nodes and run test suites against every model.

Workflow:
  1. Discover nodes (from config, env-var, or subnet scan)
  2. Query each node for available models
  3. For each (node, model) pair, run the test suites defined in
     ``config/local_models.yaml``

Usage::

    # Run everything (discover + execute)
    python scripts/run_local_models.py

    # Discover nodes only (no test execution)
    python scripts/run_local_models.py --discover-nodes

    # Discover models on known nodes
    python scripts/run_local_models.py --discover-models

    # Dry-run — show what would be executed without running
    python scripts/run_local_models.py --dry-run

Environment variables:
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Project root and sibling imports
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from scripts.discover_ollama import (  # noqa: E402
    _probe_port,
    _query_models,
)

DEFAULT_CONFIG = _project_root / "config" / "local_models.yaml"
TEST_SUITES_CONFIG = _project_root / "config" / "test_suites.yaml"


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
    from urllib.parse import urlparse

    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    return [{"hostname": host, "port": port}]


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
        List of dicts with ``hostname``, ``endpoint``, ``models`` keys.
        Only online nodes are included.
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
        return {
            "hostname": hostname,
            "endpoint": endpoint,
            "models": models,
        }

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
# Runner
# ---------------------------------------------------------------------------


def run_model_suites(
    config: dict[str, Any],
    nodes_with_models: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> list[RunResult]:
    """Run configured test suites against every (node, model) pair.

    Args:
        config: Parsed local_models.yaml.
        nodes_with_models: Output of :func:`discover_local_models`.
        dry_run: If True, print commands without executing.

    Returns:
        List of :class:`RunResult` objects.
    """
    suites = config.get("test_suites", [])
    execution = config.get("execution", {})
    continue_on_failure = execution.get("continue_on_failure", True)

    results: list[RunResult] = []

    for node_info in nodes_with_models:
        endpoint = node_info["endpoint"]
        hostname = node_info["hostname"]
        models = node_info.get("models", [])

        for model in models:
            for suite in suites:
                cmd = _build_robot_command(
                    config=config,
                    suite=suite,
                    endpoint=endpoint,
                    model=model,
                    node_name=hostname,
                )

                output_dir = (
                    config.get("execution", {})
                    .get("output_dir", "results/local/{node}/{model}")
                    .format(
                        node=_sanitize_name(hostname),
                        model=_sanitize_name(model),
                    )
                )

                if dry_run:
                    print(f"[DRY-RUN] {' '.join(cmd)}")
                    results.append(
                        RunResult(
                            node=hostname,
                            model=model,
                            suite=suite["name"],
                            returncode=0,
                            output_dir=output_dir,
                        )
                    )
                    continue

                print(
                    f"\n{'=' * 70}\n"
                    f"  Node:  {hostname}\n"
                    f"  Model: {model}\n"
                    f"  Suite: {suite['name']}\n"
                    f"{'=' * 70}\n"
                )
                print(f"  > {' '.join(cmd)}\n")

                proc = subprocess.run(cmd, cwd=str(_project_root))

                results.append(
                    RunResult(
                        node=hostname,
                        model=model,
                        suite=suite["name"],
                        returncode=proc.returncode,
                        output_dir=output_dir,
                    )
                )

                if proc.returncode != 0 and not continue_on_failure:
                    print(
                        f"\nSuite '{suite['name']}' failed for "
                        f"{model}@{hostname} (rc={proc.returncode}). "
                        f"Stopping (continue_on_failure=false)."
                    )
                    return results

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _print_summary(results: list[RunResult]) -> None:
    """Print a human-readable summary of all runs."""
    if not results:
        print("\nNo test runs were executed.")
        return

    passed = [r for r in results if r.returncode == 0]
    failed = [r for r in results if r.returncode != 0]

    print(f"\n{'=' * 70}")
    print("  Run Summary")
    print(f"{'=' * 70}")
    print(f"  Total runs: {len(results)}")
    print(f"  Passed:     {len(passed)}")
    print(f"  Failed:     {len(failed)}")

    if failed:
        print("\n  Failed runs:")
        for r in failed:
            print(f"    - {r.suite} | {r.model}@{r.node} (rc={r.returncode})")

    print()


def run_iteration_loop(
    config: dict[str, Any],
    *,
    iterations: int = 1,
    dry_run: bool = False,
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

    Returns:
        True if any pass had a test failure, False otherwise.
    """
    discovery_cfg = config.get("discovery", {})
    had_failure = False
    iteration = 0

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
            node_list = _load_node_list()
            print(f"Probing {len(node_list)} node(s)...")

            nodes_with_models = discover_local_models(
                node_list,
                connect_timeout=discovery_cfg.get("connect_timeout", 2),
                max_workers=discovery_cfg.get("max_workers", 64),
            )

            _print_discovered_nodes(nodes_with_models)

            suites = config.get("test_suites", [])
            total_models = sum(len(n["models"]) for n in nodes_with_models)
            total_runs = total_models * len(suites)

            if total_runs == 0:
                print("No models discovered — nothing to run.")
                if iterations > 0:
                    continue
                # For infinite/stop-on-error, keep trying
                continue

            print(
                f"Running {len(suites)} suite(s) x {total_models} model(s) = "
                f"{total_runs} total run(s)\n"
            )

            results = run_model_suites(config, nodes_with_models, dry_run=dry_run)
            _print_summary(results)

            pass_had_failure = any(r.returncode != 0 for r in results)
            if pass_had_failure:
                had_failure = True

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
        for m in node["models"]:
            print(f"    - {m}")

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
    args = parser.parse_args()

    config = load_local_config(Path(args.config))
    discovery_cfg = config.get("discovery", {})

    if args.discover_nodes:
        node_list = _load_node_list()
        print(f"Probing {len(node_list)} node(s)...")
        for node in node_list:
            hostname = node["hostname"]
            port = node.get("port", 11434)
            online = _probe_port(
                hostname, port, timeout=discovery_cfg.get("connect_timeout", 2)
            )
            status = "ONLINE" if online else "OFFLINE"
            print(f"  {hostname}:{port}  {status}")
        return

    if args.discover_models:
        node_list = _load_node_list()
        print(f"Probing {len(node_list)} node(s)...")
        nodes_with_models = discover_local_models(
            node_list,
            connect_timeout=discovery_cfg.get("connect_timeout", 2),
            max_workers=discovery_cfg.get("max_workers", 64),
        )
        _print_discovered_nodes(nodes_with_models)
        return

    # Run the iteration loop
    had_failure = run_iteration_loop(
        config, iterations=args.iterations, dry_run=args.dry_run
    )

    if had_failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
