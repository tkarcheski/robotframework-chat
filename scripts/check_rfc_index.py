#!/usr/bin/env python3
"""CI guard: RFC numbers are unique and registered in the index (issue #40).

RFC numbers used to be picked per-branch with no central reservation, so two
concurrent branches could each write `RFC-006-*.md` and only a human at review
would notice the collision. This guard, a sibling to
`check_agent_signoffs.py`, makes the reservation convention in
`modules/rfcs/README.md` mechanical — "prompts request, checks enforce"
(ai/GIT.md).

It scans `modules/rfcs/`, parses the index table in `modules/rfcs/README.md`,
and fails (`--check`, the default) when:

  1. two RFC *files* claim the same number — a collision;
  2. an RFC file's number is absent from the index — an unreserved RFC;
  3. the index table lists the same number twice — a double reservation.

A number that appears in the index with **no** file on this branch is allowed:
that is exactly a *reservation* (e.g. RFC-005 reserved on a side branch before
its file merges). The convention to reserve a number is therefore a one-line
PR adding a row to the index, which serializes contention through review.

Usage:
  python modules/ops/scripts/check_rfc_index.py            # --check (default)
  python modules/ops/scripts/check_rfc_index.py --check
  python modules/ops/scripts/check_rfc_index.py --dir path/to/rfcs
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# RFC files follow `RFC-<zero-padded-number>-<slug>.md`; the slug is required so
# the index/README and bare scratch files are never mistaken for an RFC.
RFC_FILENAME_RE = re.compile(r"^RFC-(\d+)-.+\.md$", re.IGNORECASE)
# A number cell inside the index table: `RFC-003`, `RFC-3`, or a bare `3`.
INDEX_NUMBER_RE = re.compile(r"^(?:RFC-)?(\d+)$", re.IGNORECASE)

DEFAULT_RFC_DIR = Path(__file__).resolve().parents[3] / "modules" / "rfcs"
INDEX_FILENAMES = ("README.md", "INDEX.md")


@dataclass(frozen=True)
class RfcFile:
    """An `RFC-<n>-*.md` document on disk."""

    number: int
    filename: str


@dataclass(frozen=True)
class IndexEntry:
    """One row's number cell parsed from the index table."""

    number: int
    raw: str


def rfc_number_from_filename(name: str) -> int | None:
    """Return the RFC number encoded in a filename, or None if it isn't one."""
    match = RFC_FILENAME_RE.match(name)
    return int(match.group(1)) if match else None


def parse_index_numbers(text: str) -> list[IndexEntry]:
    """Extract the RFC numbers from the first cell of each index-table row.

    Only genuine Markdown table rows (`| ... |`) count; a separator row
    (`|---|`) and prose mentions of `RFC-009` elsewhere in the file are
    ignored, so a sentence describing the convention can't be misread as a
    reservation.
    """
    entries: list[IndexEntry] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        # First cell of the pipe row (drop the leading empty split from `|`).
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if set(first) <= {"-", ":"}:  # separator row like |---|:--:|
            continue
        match = INDEX_NUMBER_RE.match(first)
        if match:
            entries.append(IndexEntry(number=int(match.group(1)), raw=first))
    return entries


def evaluate(files: list[RfcFile], index: list[IndexEntry]) -> list[str]:
    """One human-readable violation per numbering problem (see module docstring)."""
    violations: list[str] = []

    # 1. Duplicate RFC file numbers — the collision this guard exists to catch.
    by_number: dict[int, list[str]] = {}
    for f in files:
        by_number.setdefault(f.number, []).append(f.filename)
    for number, names in sorted(by_number.items()):
        if len(names) > 1:
            violations.append(
                f"duplicate RFC number {number:03d}: "
                f"{', '.join(sorted(names))} — two files claim the same number; "
                "rename all but one and reserve a fresh number in the index"
            )

    # 3. Duplicate index entries — a double reservation.
    index_seen: dict[int, int] = {}
    for e in index:
        index_seen[e.number] = index_seen.get(e.number, 0) + 1
    for number, count in sorted(index_seen.items()):
        if count > 1:
            violations.append(
                f"duplicate index entry for RFC number {number:03d}: listed "
                f"{count} times in the index — each number may be reserved once"
            )

    # 2. Files absent from the index — an unreserved RFC.
    index_numbers = set(index_seen)
    for f in sorted(files, key=lambda f: (f.number, f.filename)):
        if f.number not in index_numbers:
            violations.append(
                f"{f.filename} (RFC {f.number:03d}) is missing from the RFC "
                "index — add a row to modules/rfcs/README.md to reserve it"
            )

    return violations


def rfc_files_in(rfc_dir: Path) -> list[RfcFile]:
    """Every `RFC-<n>-*.md` file directly under rfc_dir (non-recursive)."""
    files: list[RfcFile] = []
    for path in sorted(rfc_dir.iterdir()):
        if not path.is_file():
            continue
        number = rfc_number_from_filename(path.name)
        if number is not None:
            files.append(RfcFile(number=number, filename=path.name))
    return files


def read_index(rfc_dir: Path) -> list[IndexEntry]:
    """Parse the index table from the first of README.md / INDEX.md that exists."""
    for name in INDEX_FILENAMES:
        candidate = rfc_dir / name
        if candidate.is_file():
            return parse_index_numbers(candidate.read_text(encoding="utf-8"))
    return []


def scan_rfc_dir(rfc_dir: Path) -> tuple[list[RfcFile], list[IndexEntry]]:
    """Collect RFC files and parsed index entries from an RFC directory."""
    return rfc_files_in(rfc_dir), read_index(rfc_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail (exit 1) on any RFC numbering violation. Default behaviour.",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_RFC_DIR,
        help=f"RFC directory to check (default: {DEFAULT_RFC_DIR}).",
    )
    args = parser.parse_args(argv)

    rfc_dir: Path = args.dir
    if not rfc_dir.is_dir():
        print(f"RFC index guard: directory not found: {rfc_dir}", file=sys.stderr)
        return 1

    files, index = scan_rfc_dir(rfc_dir)
    violations = evaluate(files, index)
    if violations:
        print("RFC numbering violations (see modules/rfcs/README.md):", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print(
        f"RFC index: ok ({len(files)} RFC file(s), "
        f"{len(index)} index entr(y/ies) checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
