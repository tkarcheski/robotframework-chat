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
    """CLI entry point: print --test flags for each skipped test.

    Uses null-delimited output (``-0`` / ``--print0``) for shell safety
    when test names contain spaces.  Default mode prints one
    ``--test <name>`` pair per line for human readability.
    """
    print0 = "-0" in sys.argv or "--print0" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("-0", "--print0")]
    if len(args) != 1:
        print("Usage: python -m rfc.rerun_skipped [-0] <output.xml>", file=sys.stderr)
        sys.exit(1)
    names = collect_skipped(args[0])
    if print0:
        for name in names:
            sys.stdout.write(f"--test\0{name}\0")
    else:
        for name in names:
            print("--test")
            print(name)


if __name__ == "__main__":
    main()
