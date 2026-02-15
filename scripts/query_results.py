"""Query test results database for analysis and reporting.

Provides various queries for analyzing test performance,
model comparisons, and historical trends.
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rfc.test_database import TestDatabase


def print_table(headers, rows):
    """Print data as formatted table."""
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    # Print header
    header_row = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_row)
    print("-" * len(header_row))

    # Print rows
    for row in rows:
        print(" | ".join(str(cell).ljust(w) for cell, w in zip(row, widths)))


def cmd_performance(db: TestDatabase, args):
    """Show model performance summary."""
    stats = db.get_model_performance(args.model)

    if not stats:
        print("No test data found")
        return

    headers = ["Model", "Runs", "Pass Rate", "Passed", "Failed", "Avg Duration"]
    rows = []
    for stat in stats:
        rows.append(
            [
                stat["model_name"],
                stat["total_runs"],
                f"{stat['avg_pass_rate']:.1f}%",
                stat["total_passed"],
                stat["total_failed"],
                f"{stat['avg_duration']:.1f}s",
            ]
        )

    print("\nModel Performance Summary")
    print("=" * 80)
    print_table(headers, rows)


def cmd_recent(db: TestDatabase, args):
    """Show recent test runs."""
    runs = db.get_recent_runs(args.limit)

    if not runs:
        print("No test runs found")
        return

    headers = ["ID", "Timestamp", "Model", "Suite", "Pass", "Fail", "Skip", "Commit"]
    rows = []
    for run in runs:
        rows.append(
            [
                run["id"],
                run["timestamp"][:19],  # Truncate to remove microseconds
                run["model_name"][:20],
                run["test_suite"][:15],
                run["passed"],
                run["failed"],
                run["skipped"],
                (run["git_commit"] or "")[:8],
            ]
        )

    print(f"\nRecent Test Runs (last {args.limit})")
    print("=" * 100)
    print_table(headers, rows)


def cmd_history(db: TestDatabase, args):
    """Show history for a specific test."""
    history = db.get_test_history(args.test_name)

    if not history:
        print(f"No history found for test: {args.test_name}")
        return

    headers = ["Timestamp", "Model", "Status", "Score"]
    rows = []
    for h in history:
        rows.append(
            [
                h["timestamp"][:19],
                h["model_name"][:20],
                h["test_status"],
                h["score"] if h["score"] is not None else "N/A",
            ]
        )

    print(f"\nTest History: {args.test_name}")
    print("=" * 80)
    print_table(headers, rows)


def cmd_compare(db: TestDatabase, args):
    """Compare performance between models."""
    # Get performance for all models
    stats = db.get_model_performance()

    if len(stats) < 2:
        print("Need at least 2 models for comparison")
        return

    print("\nModel Comparison")
    print("=" * 80)

    # Sort by pass rate
    stats.sort(key=lambda x: x["avg_pass_rate"], reverse=True)

    best = stats[0]
    print(f"\nBest Performing: {best['model_name']}")
    print(f"  Pass Rate: {best['avg_pass_rate']:.1f}%")
    print(f"  Total Tests: {best['total_passed'] + best['total_failed']}")

    if len(stats) > 1:
        print("\nAll Models:")
        for i, stat in enumerate(stats, 1):
            diff = stat["avg_pass_rate"] - best["avg_pass_rate"]
            print(
                f"  {i}. {stat['model_name']}: {stat['avg_pass_rate']:.1f}% "
                f"({diff:+.1f}% vs best)"
            )


def cmd_export(db: TestDatabase, args):
    """Export database to JSON."""
    db.export_to_json(args.output)
    print(f"Exported database to: {args.output}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Query test results database")
    parser.add_argument("--db", help="Database path (default: data/test_history.db)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Performance command
    perf_parser = subparsers.add_parser(
        "performance", help="Show model performance summary"
    )
    perf_parser.add_argument("--model", help="Filter by specific model")

    # Recent command
    recent_parser = subparsers.add_parser("recent", help="Show recent test runs")
    recent_parser.add_argument(
        "--limit", "-n", type=int, default=10, help="Number of runs to show"
    )

    # History command
    history_parser = subparsers.add_parser("history", help="Show test history")
    history_parser.add_argument("test_name", help="Name of the test to query")

    # Compare command
    subparsers.add_parser("compare", help="Compare model performance")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export database to JSON")
    export_parser.add_argument(
        "--output", "-o", default="test_export.json", help="Output file path"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize database
    db = TestDatabase(args.db)

    # Execute command
    commands = {
        "performance": cmd_performance,
        "recent": cmd_recent,
        "history": cmd_history,
        "compare": cmd_compare,
        "export": cmd_export,
    }

    if args.command in commands:
        commands[args.command](db, args)
    else:
        print(f"Unknown command: {args.command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
