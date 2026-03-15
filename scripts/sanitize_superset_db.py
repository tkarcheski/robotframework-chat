"""Sanitize (truncate) all RFC data tables in the Superset PostgreSQL database.

Removes all rows from test_runs and test_results while preserving the schema,
Superset configuration, dashboards, and charts.

Usage:
    uv run python scripts/sanitize_superset_db.py
    uv run python scripts/sanitize_superset_db.py --yes   # skip confirmation
"""

import os
import sys
from pathlib import Path

# Add src to path so we can import rfc modules.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

# Tables to truncate (order matters: children first due to FK constraints).
TABLES = ["test_results", "test_runs"]


def _get_database_url() -> str | None:
    """Resolve DATABASE_URL from environment or .env file."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # Try loading .env if not already loaded.
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv  # type: ignore[import-not-found]

            load_dotenv(env_file, override=False)
        except ImportError:
            pass
        return os.getenv("DATABASE_URL")

    return None


def _get_row_counts(url: str) -> dict[str, int]:
    """Return row counts for each table."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url, connect_args={"connect_timeout": 5})
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in TABLES:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
                counts[table] = result.scalar() or 0
            except Exception:
                counts[table] = -1
    engine.dispose()
    return counts


def _truncate_tables(url: str) -> None:
    """Truncate all RFC data tables."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url, connect_args={"connect_timeout": 5})
    with engine.begin() as conn:
        # TRUNCATE CASCADE handles FK dependencies in one statement.
        conn.execute(text("TRUNCATE TABLE test_results, test_runs CASCADE"))
    engine.dispose()


def main() -> None:
    skip_confirm = "--yes" in sys.argv or "-y" in sys.argv

    print(f"{_BOLD}Superset Database Sanitize{_RESET}")
    print("=" * 50)

    url = _get_database_url()
    if not url:
        print(f"\n{_RED}DATABASE_URL is not set.{_RESET}")
        print("Set it in .env or export it in your shell.")
        print("Example: DATABASE_URL=postgresql://rfc:changeme@localhost:5433/rfc")
        sys.exit(1)

    # Show current row counts.
    print(f"\n{_BOLD}Current data:{_RESET}")
    counts = _get_row_counts(url)
    total_rows = 0
    for table, count in counts.items():
        if count < 0:
            print(f"  {_RED}{table}: table not found{_RESET}")
        elif count == 0:
            print(f"  {_YELLOW}{table}: 0 rows (already empty){_RESET}")
        else:
            print(f"  {table}: {count:,} rows")
            total_rows += count

    if total_rows == 0:
        print(f"\n{_GREEN}Nothing to sanitize — all tables are already empty.{_RESET}")
        sys.exit(0)

    # Confirmation prompt.
    print(f"\n{_RED}{_BOLD}This will permanently delete all {total_rows:,} rows.{_RESET}")
    print("Superset dashboards, charts, and configuration will be preserved.")

    if not skip_confirm:
        try:
            answer = input(f"\n{_BOLD}Are you sure? [y/N]: {_RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)

        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(1)

    # Truncate.
    print(f"\n{_BOLD}Sanitizing...{_RESET}")
    try:
        _truncate_tables(url)
    except Exception as e:
        print(f"{_RED}Failed to truncate tables: {e}{_RESET}")
        sys.exit(1)

    # Verify.
    counts_after = _get_row_counts(url)
    print(f"\n{_BOLD}After sanitize:{_RESET}")
    for table, count in counts_after.items():
        print(f"  {_GREEN}{table}: {count} rows{_RESET}")

    print(f"\n{_GREEN}Sanitize complete.{_RESET} Flush the Redis cache to refresh dashboards:")
    print("  make cache-flush")


if __name__ == "__main__":
    main()
