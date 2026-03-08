"""Cross-platform task runner — essential targets for Windows users.

Usage:
    uv run python tasks.py <target>
    uv run python tasks.py help          # list all targets

Provides the core targets needed to run Robot Framework tests, discover
and test local models, and upload results to Apache Superset.  Works on
Windows, macOS, and Linux without ``make``, ``bash``, or other Unix tools.
"""

from __future__ import annotations

import argparse
import os
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
    "rfc.chat_log_listener.ChatLogListener",
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


def _ensure_env() -> None:
    """Copy ``.env.example`` → ``.env`` if missing, then load into environ."""
    env_file = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_file.exists() and example.exists():
        shutil.copy2(str(example), str(env_file))
        print("  Created .env from .env.example — edit it if needed.")
    if env_file.exists():
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv(env_file, override=False)


# ── Targets ──────────────────────────────────────────────────────────


def install() -> None:
    """Install Python dependencies."""
    _uv("sync", "--extra", "dev", "--extra", "superset")


def update() -> None:
    """Fetch and pull latest changes from remote."""
    _run(["git", "fetch"])
    _run(["git", "pull"])


def robot() -> None:
    """Run all Robot Framework test suites."""
    robot_math()
    robot_accounting()
    robot_safety()


def robot_math() -> None:
    """Run math tests (Robot Framework)."""
    _ensure_env()
    _uv_run("robot", "-d", "results/math", *LISTENERS, "robot/math/tests/")


def robot_accounting() -> None:
    """Run accounting tests (Robot Framework)."""
    _ensure_env()
    _uv_run("robot", "-d", "results/accounting", *LISTENERS, "robot/accounting/tests/")


def robot_safety() -> None:
    """Run safety tests (Robot Framework)."""
    _ensure_env()
    _uv_run("robot", "-d", "results/safety", *LISTENERS, "robot/safety/")


def robot_dryrun() -> None:
    """Validate all Robot tests (dry run, no execution)."""
    _ensure_env()
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


def run_local_models() -> None:
    """Run test suites against every model on every local node."""
    _ensure_env()
    cmd: list[str] = ["python", "scripts/run_local_models.py"]
    iterations = os.environ.get("ITERATIONS")
    if iterations:
        cmd.extend(["--iterations", iterations])
    _uv_run(*cmd)


def import_results() -> None:
    """Import output.xml results into the Superset database."""
    _ensure_env()
    results_path = os.environ.get("RESULTS_PATH", "results/")
    cmd: list[str] = [
        "python",
        "scripts/import_test_results.py",
        results_path,
        "--recursive",
    ]
    model = os.environ.get("DEFAULT_MODEL")
    if model:
        cmd.extend(["--model", model])
    _uv_run(*cmd)


def docker_build_app() -> None:
    """Build the application Docker image locally."""
    _run(["docker", "build", "-t", "ghcr.io/tkarcheski/robotframework-chat:local", "."])


def docker_test_app() -> None:
    """Smoke-test the application Docker image (dry-run)."""
    docker_build_app()
    _run(
        [
            "docker",
            "run",
            "--rm",
            "ghcr.io/tkarcheski/robotframework-chat:local",
            "make",
            "robot-dryrun",
        ]
    )


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
    "update": update,
    "robot": robot,
    "robot-math": robot_math,
    "robot-accounting": robot_accounting,
    "robot-safety": robot_safety,
    "robot-dryrun": robot_dryrun,
    "run-local-models": run_local_models,
    "import-results": import_results,
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
