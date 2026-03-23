"""Check Robot Framework test tag compliance in output.xml files.

Every test must have exactly one ``tier:*`` (0-6) and one ``verify:*``
(robot|python|llm|llms) tag.  Parses output.xml via the Robot Framework
API and reports violations with a non-zero exit code for CI gating.

Usage:
    uv run python scripts/robot_review.py [output.xml ...]
    uv run python scripts/robot_review.py results/dryrun/output.xml
    uv run python scripts/robot_review.py --quiet results/*/output.xml
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from robot.api import ExecutionResult  # type: ignore[import-not-found]
from robot.errors import DataError  # type: ignore[import-not-found]
from robot.result.model import TestCase, TestSuite  # type: ignore[import-not-found]

VALID_TIERS: set[int] = {0, 1, 2, 3, 4, 5, 6}
VALID_VERIFY: set[str] = {"robot", "python", "llm", "llms"}


@dataclass
class Violation:
    """A single test that violates tag compliance rules."""

    test_name: str
    suite_name: str
    issues: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    """Aggregated compliance result for one output.xml file."""

    total_tests: int
    compliant: int
    violations: list[Violation]
    file_path: str


def check_test(test_name: str, suite_name: str, tags: list[str]) -> Violation | None:
    """Check a single test's tags for compliance.

    Returns a Violation if non-compliant, or None if the test passes.
    """
    issues: list[str] = []

    # Robot Framework tags are case-insensitive; normalize before matching.
    normalized = [t.lower() for t in tags]
    tier_tags = [t for t in normalized if t.startswith("tier:")]
    verify_tags = [t for t in normalized if t.startswith("verify:")]

    # Duplicate detection
    if len(tier_tags) > 1:
        issues.append(f"multiple tier:* tags ({', '.join(tier_tags)})")
    if len(verify_tags) > 1:
        issues.append(f"multiple verify:* tags ({', '.join(verify_tags)})")

    # Tier validation
    if len(tier_tags) == 0:
        issues.append("missing tier:* tag")
    elif len(tier_tags) == 1:
        raw = tier_tags[0].split(":", 1)[1]
        try:
            tier_val = int(raw)
            if tier_val not in VALID_TIERS:
                issues.append(f"invalid tier value: {tier_val} (expected 0-6)")
        except ValueError:
            issues.append(f"non-numeric tier value: {raw}")

    # Verify validation
    if len(verify_tags) == 0:
        issues.append("missing verify:* tag")
    elif len(verify_tags) == 1:
        verify_val = verify_tags[0].split(":", 1)[1]
        if verify_val not in VALID_VERIFY:
            issues.append(
                f"invalid verify value: {verify_val} "
                f"(expected {', '.join(sorted(VALID_VERIFY))})"
            )

    if issues:
        return Violation(test_name=test_name, suite_name=suite_name, issues=issues)
    return None


def _collect_tests(
    suite: TestSuite,
) -> list[tuple[str, str, list[str]]]:
    """Recursively collect (test_name, suite_name, tags) from a suite tree."""
    tests: list[tuple[str, str, list[str]]] = []
    for test in suite.tests:
        assert isinstance(test, TestCase)
        tests.append((test.name, suite.name, list(test.tags)))
    for child in suite.suites:
        tests.extend(_collect_tests(child))
    return tests


def review_output_xml(path: str) -> ReviewResult:
    """Parse an output.xml file and check all tests for tag compliance.

    Raises:
        FileNotFoundError: If the path does not exist.
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"output.xml not found: {path}")

    result = ExecutionResult(path)
    all_tests = _collect_tests(result.suite)

    violations: list[Violation] = []
    for test_name, suite_name, tags in all_tests:
        v = check_test(test_name, suite_name, tags)
        if v is not None:
            violations.append(v)

    compliant = len(all_tests) - len(violations)
    return ReviewResult(
        total_tests=len(all_tests),
        compliant=compliant,
        violations=violations,
        file_path=path,
    )


def print_report(results: list[ReviewResult], *, quiet: bool = False) -> None:
    """Print a compliance report to stdout."""
    total_all = sum(r.total_tests for r in results)
    compliant_all = sum(r.compliant for r in results)
    violations_all = sum(len(r.violations) for r in results)

    print("\nTag Compliance Report")
    print("=" * 60)

    for r in results:
        if len(results) > 1:
            print(f"\nFile: {r.file_path}")
            print("-" * 60)

        pct = (r.compliant / r.total_tests * 100) if r.total_tests else 0
        print(f"  Total tests:  {r.total_tests}")
        print(f"  Compliant:    {r.compliant} ({pct:.1f}%)")
        print(f"  Violations:   {len(r.violations)}")

        if not quiet and r.violations:
            print()
            for v in r.violations:
                print(f"  FAIL  {v.test_name}")
                print(f"        Suite: {v.suite_name}")
                for issue in v.issues:
                    print(f"        - {issue}")
                print()

    if len(results) > 1:
        print("=" * 60)
        total_pct = (compliant_all / total_all * 100) if total_all else 0
        print(f"  TOTAL: {compliant_all}/{total_all} compliant ({total_pct:.1f}%)")

    print("=" * 60)
    if violations_all == 0:
        print("  PASS: All tests have valid tier:* and verify:* tags.")
    else:
        print(f"  FAIL: {violations_all} test(s) with tag violations.")
    print()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Check Robot Framework test tag compliance in output.xml files.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["results/dryrun/output.xml"],
        help="output.xml file path(s) to check (default: results/dryrun/output.xml)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only print summary, not individual violations",
    )
    return parser


def main() -> int:
    """Entry point. Returns 0 if compliant, 1 if violations, 2 if file error."""
    args = build_parser().parse_args()

    results: list[ReviewResult] = []
    for path in args.paths:
        try:
            results.append(review_output_xml(path))
        except (FileNotFoundError, DataError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    print_report(results, quiet=args.quiet)

    total_violations = sum(len(r.violations) for r in results)
    return 1 if total_violations > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
