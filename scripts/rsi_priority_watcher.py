#!/usr/bin/env python
"""Prioritized RSI-model test lane.

Goal: "keep testing running 24/7, prioritize the RSI model when it updates."

The main ``run-local-models`` forever loop already exercises every discovered
model, but it treats the RSI model like any other entry in a long model-major
queue and never inspects Ollama digests -- so a freshly re-published
``rsi-qwen:round`` is not re-tested until the general rotation reaches it again.

This watcher gives the RSI model a dedicated fast lane. Each cycle it polls
``GET /api/tags`` on every curated host, and whenever the RSI model's digest
changes (or is seen for the first time) it immediately runs the model against a
curated suite set, reusing the exact ``uv run robot`` invocation and listeners
that ``run-local-models`` uses, so results archive to Postgres identically.

Run it alongside the main loop::

    uv run python scripts/rsi_priority_watcher.py                # forever, fast subset
    uv run python scripts/rsi_priority_watcher.py --all-suites   # forever, every suite
    uv run python scripts/rsi_priority_watcher.py --once --dry-run   # smoke test

The pure update-detection logic lives in :mod:`rfc.rsi_priority` and is unit
tested in ``tests/test_rsi_priority.py``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Project root and sibling imports (mirror run_local_models.py)
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from rfc.host_scheduler import load_host_config  # noqa: E402
from rfc.rsi_priority import (  # noqa: E402
    DEFAULT_RSI_MODEL,
    extract_digest,
    needs_retest,
)
from scripts.run_local_models import (  # noqa: E402
    _build_robot_command,
    load_local_config,
    preflight_model,
)

#: Fast, cheap default suites for quick RSI feedback on each update. The main
#: 24/7 loop still covers the full matrix; this lane favours latency. Override
#: with --suites or run everything with --all-suites.
DEFAULT_FAST_SUITES = ["math", "accounting", "safety", "refusal-calibration"]

#: Default watch target: the local Ollama instance that produces the RSI model.
#: It serves ``rsi-qwen:round`` and is NOT one of the curated fleet hosts, so the
#: main 24/7 loop never touches it -- giving the RSI lane a genuinely
#: uncontended slot (a generate returns in seconds instead of queueing behind
#: the fleet's work on a saturated host). Add fleet hosts with --host-config.
DEFAULT_ENDPOINTS = [("localhost", "http://localhost:11434")]

#: Poll cadence between /api/tags checks when idle (seconds).
DEFAULT_INTERVAL = 120

#: HTTP read budget for the lightweight /api/tags poll (seconds).
DEFAULT_REQUEST_TIMEOUT = 10

#: Fast-lane preflight budget (seconds). Kept short so a preflight probe fails
#: fast on a busy host rather than blocking the loop for the main run's 30 min.
DEFAULT_PREFLIGHT_TIMEOUT = 300


def _log(msg: str) -> None:
    """Timestamped stdout line (stdout is teed to the watcher logfile)."""
    print(f"[rsi-watcher] {msg}", flush=True)


def _select_suites(
    config: dict[str, Any], *, names: list[str] | None, all_suites: bool
) -> list[dict[str, Any]]:
    """Resolve the suite dicts to run, from the local-models config.

    Args:
        config: Parsed ``config/local_models.yaml``.
        names: Explicit suite names to run, or ``None`` for the default set.
        all_suites: When ``True``, run every configured suite (``names`` ignored).

    Returns:
        The selected suite dicts (each with at least ``name`` and ``path``).
    """
    suites = config.get("test_suites", [])
    if all_suites:
        return list(suites)
    wanted = names if names else DEFAULT_FAST_SUITES
    by_name = {s["name"]: s for s in suites}
    selected = [by_name[n] for n in wanted if n in by_name]
    missing = [n for n in wanted if n not in by_name]
    if missing:
        _log(f"WARNING: suites not in config, skipping: {', '.join(missing)}")
    return selected


def _fetch_digest(endpoint: str, model: str, *, timeout: float) -> str | None:
    """Poll one host's /api/tags and return the model's digest (or None).

    Network/parse errors are swallowed and logged so the forever loop keeps
    running when a host is briefly unreachable.
    """
    url = f"{endpoint.rstrip('/')}/api/tags"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return extract_digest(resp.json(), model)
    except Exception as exc:  # noqa: BLE001 - resilience over precision here
        _log(f"poll failed for {endpoint}: {exc.__class__.__name__}: {exc}")
        return None


def _run_rsi_suites(
    *,
    config: dict[str, Any],
    suites: list[dict[str, Any]],
    endpoint: str,
    model: str,
    node_name: str,
    dry_run: bool,
) -> int:
    """Run the selected suites for ``model`` on one host. Returns failure count."""
    failures = 0
    for suite in suites:
        cmd = _build_robot_command(
            config=config,
            suite=suite,
            endpoint=endpoint,
            model=model,
            node_name=node_name,
        )
        if dry_run:
            _log(f"DRY-RUN would run [{node_name}/{suite['name']}]: {' '.join(cmd)}")
            continue
        _log(f"running [{node_name}/{suite['name']}] against {model} @ {endpoint}")
        proc = subprocess.run(cmd, cwd=_project_root)  # noqa: S603
        if proc.returncode != 0:
            failures += 1
            _log(f"suite [{node_name}/{suite['name']}] returncode={proc.returncode}")
    return failures


def _parse_endpoint(spec: str) -> tuple[str, str]:
    """Parse a ``NAME=URL`` --endpoint value into a (name, url) pair."""
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            f"--endpoint must be NAME=URL, got: {spec!r}"
        )
    name, url = spec.split("=", 1)
    name, url = name.strip(), url.strip()
    if not name or not url:
        raise argparse.ArgumentTypeError(
            f"--endpoint must be NAME=URL, got: {spec!r}"
        )
    return name, url


def _resolve_hosts(args: argparse.Namespace) -> list[tuple[str, str]]:
    """Build the (name, endpoint) watch list from --endpoint and --host-config.

    Defaults to the uncontended local Ollama; fleet hosts from a host-config.toml
    are appended only when --host-config is given.
    """
    hosts: list[tuple[str, str]] = list(args.endpoint or DEFAULT_ENDPOINTS)
    if args.host_config:
        host_config = load_host_config(Path(args.host_config))
        hosts += [(h.name, h.endpoint) for h in host_config.hosts]
    return hosts


def watch(args: argparse.Namespace) -> int:
    """Main poll/react loop. Returns a process exit code."""
    config = load_local_config()
    suites = _select_suites(
        config, names=args.suites, all_suites=args.all_suites
    )
    if not suites:
        _log("no suites selected; nothing to do")
        return 1

    hosts = _resolve_hosts(args)
    _log(
        f"watching '{args.model}' on {len(hosts)} host(s) "
        f"[{', '.join(n for n, _ in hosts)}] every {args.interval}s; "
        f"{len(suites)} suite(s) per update "
        f"[{', '.join(s['name'] for s in suites)}]"
        + (" (dry-run)" if args.dry_run else "")
    )

    last_digest: dict[str, str] = {}
    cycle = 0
    try:
        while True:
            cycle += 1
            for name, endpoint in hosts:
                digest = _fetch_digest(
                    endpoint, args.model, timeout=args.request_timeout
                )
                if not needs_retest(last_digest.get(name), digest):
                    continue
                prev = last_digest.get(name, "<none>")
                _log(f"RSI update on {name}: {prev} -> {digest} (cycle {cycle})")

                if args.preflight and not args.dry_run:
                    ok, detail = preflight_model(
                        endpoint, args.model, timeout=args.preflight_timeout
                    )
                    if not ok:
                        _log(
                            f"preflight FAILED on {name} ({detail}); "
                            f"recording digest, skipping suites this cycle"
                        )
                        last_digest[name] = digest  # type: ignore[assignment]
                        continue

                failures = _run_rsi_suites(
                    config=config,
                    suites=suites,
                    endpoint=endpoint,
                    model=args.model,
                    node_name=name,
                    dry_run=args.dry_run,
                )
                last_digest[name] = digest  # type: ignore[assignment]
                _log(
                    f"RSI run complete on {name}: "
                    f"{len(suites) - failures}/{len(suites)} suites passed"
                )

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        _log(f"interrupted after {cycle} cycle(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--model",
        default=DEFAULT_RSI_MODEL,
        help=f"RSI model tag to watch (default: {DEFAULT_RSI_MODEL})",
    )
    p.add_argument(
        "--endpoint",
        action="append",
        type=_parse_endpoint,
        metavar="NAME=URL",
        help="Ollama endpoint to watch as NAME=URL (repeatable). "
        "Default: localhost=http://localhost:11434 (uncontended lane)",
    )
    p.add_argument(
        "--host-config",
        default=None,
        help="Optional host-config.toml whose fleet hosts are ALSO watched "
        "(note: fleet hosts may be saturated by the main run-local-models loop)",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between polls (default: {DEFAULT_INTERVAL})",
    )
    p.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help=f"/api/tags HTTP timeout (default: {DEFAULT_REQUEST_TIMEOUT})",
    )
    p.add_argument(
        "--suites",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        default=None,
        help="Comma-separated suite names to run on update "
        f"(default: {','.join(DEFAULT_FAST_SUITES)})",
    )
    p.add_argument(
        "--all-suites",
        action="store_true",
        help="Run every configured suite on update instead of the fast subset",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle and exit (for smoke tests)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the robot commands that would run, without executing them",
    )
    preflight = p.add_mutually_exclusive_group()
    preflight.add_argument(
        "--preflight",
        dest="preflight",
        action="store_true",
        default=False,
        help="Probe the model before running suites. Off by default so a "
        "regressed RSI update still runs the suites (and records failures) "
        "instead of being silently skipped",
    )
    preflight.add_argument(
        "--no-preflight",
        dest="preflight",
        action="store_false",
        help="Explicitly disable the preflight probe (the default)",
    )
    p.add_argument(
        "--preflight-timeout",
        type=float,
        default=DEFAULT_PREFLIGHT_TIMEOUT,
        help=f"Preflight probe budget in seconds (default: {DEFAULT_PREFLIGHT_TIMEOUT})",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    return watch(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
