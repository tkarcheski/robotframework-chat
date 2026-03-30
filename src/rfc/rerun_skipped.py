"""Extract --test flags for skipped tests from a Robot Framework output.xml."""

from __future__ import annotations

import sys

from robot.api import ExecutionResult
from robot.result import TestSuite


def collect_skipped(output_path: str) -> list[str]:
    """Return full names of skipped tests from output.xml."""
    result = ExecutionResult(output_path)
    skipped: list[str] = []

    def _visit(suite: TestSuite) -> None:
        for test in suite.tests:
            if test.status == "SKIP":
                skipped.append(test.full_name)
        for child in suite.suites:
            _visit(child)

    _visit(result.suite)
    return skipped


def main() -> None:
    """CLI entry point: print --test flags for each skipped test."""
    if len(sys.argv) != 2:
        print("Usage: python -m rfc.rerun_skipped <output.xml>", file=sys.stderr)
        sys.exit(1)
    for name in collect_skipped(sys.argv[1]):
        print("--test")
        print(name)


if __name__ == "__main__":
    main()
