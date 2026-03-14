"""Rebot merge orchestrator with provenance tracking.

Discovers output.xml files across result directories, merges them
using Robot Framework's ``rebot`` command, and records merge
provenance (which source files were combined).

Usage::

    uv run python -m rfc.rebot_merger results/
    uv run python -m rfc.rebot_merger results/math results/docker --name "Sprint 42"

    # or via Makefile:
    make rebot-merge DIRS="results/math results/docker"
    make rebot-merge-all
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MergeConfig:
    """Configuration for a rebot merge operation."""

    source_dirs: list[str]
    output_dir: str = "results/combined"
    name: str = "Combined Results"
    merge_tag: Optional[str] = None


@dataclass
class MergeResult:
    """Result of a rebot merge operation."""

    output_path: str
    log_path: str
    report_path: str
    source_files: list[str]
    source_count: int
    return_code: int
    merged_at: datetime = field(default_factory=datetime.now)


def find_output_files(dirs: list[str]) -> list[str]:
    """Recursively discover output.xml files in given directories.

    Deduplicates by absolute path to avoid processing the same file
    twice when directories overlap.

    Args:
        dirs: List of directories to search.

    Returns:
        Sorted list of unique output.xml file paths.
    """
    seen: set[str] = set()
    result: list[str] = []

    for d in dirs:
        if not os.path.isdir(d):
            logger.warning("Directory not found, skipping: %s", d)
            continue
        for root, _subdirs, files in os.walk(d):
            for fname in files:
                if fname == "output.xml":
                    full_path = os.path.abspath(os.path.join(root, fname))
                    if full_path not in seen:
                        seen.add(full_path)
                        result.append(full_path)

    return sorted(result)


def _run_rebot(args: list[str]) -> int:
    """Run rebot via subprocess and return exit code.

    Uses ``uv run rebot`` to ensure the correct environment.
    The ``--nostatusrc`` flag is NOT used here so the caller
    can detect merge failures.
    """
    cmd = ["uv", "run", "rebot"] + args
    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout)
    if result.stderr:
        logger.warning(result.stderr)
    return result.returncode


def merge_outputs(config: MergeConfig) -> Optional[MergeResult]:
    """Merge multiple output.xml files using rebot.

    Args:
        config: Merge configuration with source dirs and output settings.

    Returns:
        MergeResult with paths and provenance, or None if no files found.
    """
    source_files = find_output_files(config.source_dirs)

    if not source_files:
        logger.warning("No output.xml files found in: %s", config.source_dirs)
        return None

    logger.info(
        "Merging %d output.xml file(s) into %s",
        len(source_files),
        config.output_dir,
    )
    for f in source_files:
        logger.info("  Source: %s", f)

    os.makedirs(config.output_dir, exist_ok=True)

    output_path = os.path.join(config.output_dir, "output.xml")
    log_path = os.path.join(config.output_dir, "log.html")
    report_path = os.path.join(config.output_dir, "report.html")

    rebot_args = [
        "--name", config.name,
        "--outputdir", config.output_dir,
        "--output", "output.xml",
        "--log", "log.html",
        "--report", "report.html",
        "--nostatusrc",
    ] + source_files

    rc = _run_rebot(rebot_args)

    return MergeResult(
        output_path=output_path,
        log_path=log_path,
        report_path=report_path,
        source_files=source_files,
        source_count=len(source_files),
        return_code=rc,
    )


def main() -> None:
    """CLI entry point for rebot merge."""
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Merge multiple Robot Framework output.xml files with rebot"
    )
    parser.add_argument(
        "dirs",
        nargs="+",
        help="Directories containing output.xml files",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="results/combined",
        help="Output directory for merged results (default: results/combined)",
    )
    parser.add_argument(
        "--name", "-n",
        default="Combined Results",
        help="Name for the combined report (default: 'Combined Results')",
    )

    args = parser.parse_args()

    config = MergeConfig(
        source_dirs=args.dirs,
        output_dir=args.output_dir,
        name=args.name,
    )

    print("=== Rebot Merge ===")
    print(f"Source dirs: {', '.join(config.source_dirs)}")
    print(f"Output dir:  {config.output_dir}")
    print(f"Report name: {config.name}")
    print()

    result = merge_outputs(config)

    if result is None:
        print("No output.xml files found to merge.")
        raise SystemExit(1)

    print()
    print("=== Merge Complete ===")
    print(f"Sources merged: {result.source_count}")
    print(f"Return code:    {result.return_code}")
    print(f"Report:         {result.report_path}")
    print(f"Log:            {result.log_path}")
    print(f"Output:         {result.output_path}")


if __name__ == "__main__":
    main()
