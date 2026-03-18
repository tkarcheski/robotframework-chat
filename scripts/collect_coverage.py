"""Parse pytest-cov JSON output and insert coverage data into PostgreSQL.

Usage:
    uv run python scripts/collect_coverage.py [--json-path coverage.json]

Generates coverage.json if it doesn't exist by running:
    uv run pytest --cov --cov-report=json

Then parses the JSON and inserts summary + per-module rows into the
``coverage_reports`` table.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Add project root to path for version import
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


def parse_coverage_json(
    json_path: Path,
) -> tuple[dict[str, int | float], list[dict[str, str | int | float]]]:
    """Parse a pytest-cov JSON report into summary and module data.

    Args:
        json_path: Path to coverage.json file.

    Returns:
        Tuple of (summary_dict, modules_list).
        summary_dict has keys: total_statements, total_covered, total_missed,
            coverage_pct.
        modules_list is a list of dicts with keys: module_name,
            module_statements, module_covered, module_missed,
            module_coverage_pct.

    Raises:
        FileNotFoundError: If json_path doesn't exist.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"Coverage JSON not found: {json_path}")

    data = json.loads(json_path.read_text())
    totals = data.get("totals", {})

    summary: dict[str, int | float] = {
        "total_statements": int(totals.get("num_statements", 0)),
        "total_covered": int(totals.get("covered_lines", 0)),
        "total_missed": int(totals.get("missing_lines", 0)),
        "coverage_pct": float(totals.get("percent_covered", 0.0)),
    }

    modules: list[dict[str, str | int | float]] = []
    for file_path, file_data in data.get("files", {}).items():
        file_summary = file_data.get("summary", {})
        modules.append(
            {
                "module_name": file_path,
                "module_statements": int(file_summary.get("num_statements", 0)),
                "module_covered": int(file_summary.get("covered_lines", 0)),
                "module_missed": int(file_summary.get("missing_lines", 0)),
                "module_coverage_pct": float(
                    file_summary.get("percent_covered", 0.0)
                ),
            }
        )

    return summary, modules


def insert_coverage_rows(
    database_url: str,
    summary: dict[str, int | float],
    modules: list[dict[str, str | int | float]],
    git_commit: str = "",
    git_branch: str = "",
    hostname: str = "",
    rfc_version: str = "",
) -> None:
    """Insert coverage data into the coverage_reports table.

    Inserts one summary row (module_name='') and one row per module.

    Args:
        database_url: SQLAlchemy connection string.
        summary: Summary coverage data from parse_coverage_json.
        modules: Per-module coverage data from parse_coverage_json.
        git_commit: Current git commit hash.
        git_branch: Current git branch.
        hostname: Machine hostname.
        rfc_version: RFC package version.
    """
    engine = create_engine(database_url)
    now = datetime.now(tz=timezone.utc).isoformat()

    insert_sql = text("""
        INSERT INTO coverage_reports (
            timestamp, git_commit, git_branch, hostname, rfc_version,
            total_statements, total_missed, total_covered, coverage_pct,
            module_name, module_statements, module_missed, module_covered,
            module_coverage_pct
        ) VALUES (
            :timestamp, :git_commit, :git_branch, :hostname, :rfc_version,
            :total_statements, :total_missed, :total_covered, :coverage_pct,
            :module_name, :module_statements, :module_missed, :module_covered,
            :module_coverage_pct
        )
    """)

    common = {
        "timestamp": now,
        "git_commit": git_commit,
        "git_branch": git_branch,
        "hostname": hostname,
        "rfc_version": rfc_version,
    }

    with engine.begin() as conn:
        # Summary row (module_name='')
        conn.execute(
            insert_sql,
            {
                **common,
                "total_statements": summary["total_statements"],
                "total_missed": summary["total_missed"],
                "total_covered": summary["total_covered"],
                "coverage_pct": summary["coverage_pct"],
                "module_name": "",
                "module_statements": 0,
                "module_missed": 0,
                "module_covered": 0,
                "module_coverage_pct": 0.0,
            },
        )
        log.info(
            "Inserted coverage summary: %.1f%% (%d/%d statements)",
            summary["coverage_pct"],
            summary["total_covered"],
            summary["total_statements"],
        )

        # Per-module rows
        for mod in modules:
            conn.execute(
                insert_sql,
                {
                    **common,
                    "total_statements": summary["total_statements"],
                    "total_missed": summary["total_missed"],
                    "total_covered": summary["total_covered"],
                    "coverage_pct": summary["coverage_pct"],
                    "module_name": mod["module_name"],
                    "module_statements": mod["module_statements"],
                    "module_missed": mod["module_missed"],
                    "module_covered": mod["module_covered"],
                    "module_coverage_pct": mod["module_coverage_pct"],
                },
            )

        log.info("Inserted %d module coverage rows.", len(modules))

    engine.dispose()


def _get_git_info() -> tuple[str, str]:
    """Get current git commit and branch."""
    try:
        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = ""

    try:
        branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        branch = ""

    return commit, branch


def main() -> None:
    """CLI entrypoint: generate coverage JSON and insert into database."""
    parser = argparse.ArgumentParser(
        description="Collect pytest coverage data and store in PostgreSQL."
    )
    parser.add_argument(
        "--json-path",
        type=Path,
        default=Path("coverage.json"),
        help="Path to coverage.json (default: coverage.json)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.getenv("DATABASE_URL", ""),
        help="Database URL (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Run pytest --cov to generate coverage.json first",
    )
    args = parser.parse_args()

    if args.generate or not args.json_path.exists():
        log.info("Generating coverage.json via pytest...")
        subprocess.run(
            [
                "uv",
                "run",
                "pytest",
                "--cov",
                "--cov-report=json",
                "--cov-report=term-missing",
            ],
            check=True,
        )

    if not args.json_path.exists():
        log.error("coverage.json not found at %s", args.json_path)
        sys.exit(1)

    if not args.database_url:
        log.error("DATABASE_URL not set. Use --database-url or set DATABASE_URL env.")
        sys.exit(1)

    summary, modules = parse_coverage_json(args.json_path)
    git_commit, git_branch = _get_git_info()

    try:
        from rfc import __version__

        rfc_version = __version__
    except ImportError:
        rfc_version = ""

    insert_coverage_rows(
        database_url=args.database_url,
        summary=summary,
        modules=modules,
        git_commit=git_commit,
        git_branch=git_branch,
        hostname=platform.node(),
        rfc_version=rfc_version,
    )

    log.info(
        "Coverage collection complete: %.1f%% overall, %d modules.",
        summary["coverage_pct"],
        len(modules),
    )


if __name__ == "__main__":
    main()
