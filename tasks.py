"""Cross-platform task runner — replaces Makefile for Windows users.

Usage:
    uv run python tasks.py <target>
    uv run python tasks.py help          # list all targets

This script mirrors the most-used Makefile targets using only the
Python standard library, so it works on Windows, macOS, and Linux
without requiring ``make``, ``bash``, or any other Unix tools.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

# ── Constants ────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent

LISTENERS = [
    "--listener",
    "rfc.db_listener.DbListener",
    "--listener",
    "rfc.git_metadata_listener.GitMetaData",
    "--listener",
    "rfc.ollama_timestamp_listener.OllamaTimestampListener",
    "--listener",
    "rfc.loki_listener.LokiListener",
]

DRYRUN_LISTENER = ["--listener", "rfc.dry_run_listener.DryRunListener"]


# ── Helpers ──────────────────────────────────────────────────────────


def _run(args: list[str], *, check: bool = True) -> int:
    """Print and execute a command, returning the exit code."""
    print(f"  → {' '.join(args)}")
    result = subprocess.run(args, cwd=str(ROOT))
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result.returncode


def _uv(*args: str, check: bool = True) -> int:
    """Run a ``uv`` subcommand."""
    return _run(["uv", *args], check=check)


def _uv_run(*args: str, check: bool = True) -> int:
    """Run a tool via ``uv run``."""
    return _run(["uv", "run", *args], check=check)


def _docker_compose(*args: str, check: bool = True) -> int:
    """Run a ``docker compose`` subcommand."""
    return _run(["docker", "compose", *args], check=check)


def _ensure_env() -> None:
    """Copy ``.env.example`` → ``.env`` if ``.env`` doesn't exist."""
    env_file = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_file.exists() and example.exists():
        shutil.copy2(str(example), str(env_file))
        print("  Created .env from .env.example — edit it if needed.")


# ── Targets ──────────────────────────────────────────────────────────


def install() -> None:
    """Install Python dependencies."""
    _uv("sync", "--extra", "dev", "--extra", "superset")


def robot() -> None:
    """Run all Robot Framework test suites."""
    robot_math()
    robot_docker()
    robot_safety()


def robot_math() -> None:
    """Run math tests (Robot Framework)."""
    _uv_run("robot", "-d", "results/math", *LISTENERS, "robot/math/tests/")


def robot_docker() -> None:
    """Run Docker tests (Robot Framework)."""
    _uv_run("robot", "-d", "results/docker", *LISTENERS, "robot/docker/")


def robot_safety() -> None:
    """Run safety tests (Robot Framework)."""
    _uv_run("robot", "-d", "results/safety", *LISTENERS, "robot/safety/")


def robot_dryrun() -> None:
    """Validate all Robot tests (dry run, no execution)."""
    _uv_run(
        "robot",
        "--dryrun",
        "--exclude",
        "browser",
        "-d",
        "results/dryrun",
        *DRYRUN_LISTENER,
        "robot/",
    )


def lint() -> None:
    """Run ruff linter."""
    _uv_run("ruff", "check", ".")


def format_code() -> None:
    """Auto-format code with ruff."""
    _uv_run("ruff", "format", ".")


def typecheck() -> None:
    """Run mypy type checker."""
    _uv_run("mypy", "src/")


def coverage() -> None:
    """Run pytest with coverage report."""
    _uv_run("pytest", "--cov", "--cov-report=term-missing", "--cov-report=html:htmlcov")


def check() -> None:
    """Run all code quality checks (lint + typecheck + coverage)."""
    lint()
    typecheck()
    coverage()


def docker_up() -> None:
    """Start PostgreSQL + Redis + Superset + Grafana."""
    _ensure_env()
    _docker_compose("up", "-d")


def docker_down() -> None:
    """Stop all services."""
    _docker_compose("down")


def show_help() -> None:
    """Show available targets."""
    print("\nAvailable targets:\n")
    max_name = max(len(name) for name in TARGETS)
    for name, func in TARGETS.items():
        doc = func.__doc__ or ""
        print(f"  {name:<{max_name + 2}} {doc}")
    print()


# ── Target registry ─────────────────────────────────────────────────

TARGETS: dict[str, object] = {
    "install": install,
    "robot": robot,
    "robot-math": robot_math,
    "robot-docker": robot_docker,
    "robot-safety": robot_safety,
    "robot-dryrun": robot_dryrun,
    "lint": lint,
    "format": format_code,
    "typecheck": typecheck,
    "coverage": coverage,
    "check": check,
    "docker-up": docker_up,
    "docker-down": docker_down,
    "help": show_help,
}


# ── Entry point ──────────────────────────────────────────────────────


def main() -> NoReturn:
    parser = argparse.ArgumentParser(
        description="Cross-platform task runner (replaces Makefile).",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="help",
        choices=list(TARGETS),
        help="Target to run (default: help)",
    )
    args = parser.parse_args()

    target_fn = TARGETS[args.target]
    assert callable(target_fn)
    target_fn()
    sys.exit(0)


if __name__ == "__main__":
    main()
