"""Tests for the LIMIT 0 column probe fallback in bootstrap_dashboards.py.

When Superset's fetch_metadata() fails on virtual datasets with empty
underlying tables, _probe_columns() discovers column names by executing
the SQL with LIMIT 0 — PostgreSQL infers types from the query plan.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Import the function under test.  bootstrap_dashboards lives outside
# src/rfc/ and imports Superset internals at call-sites, so we add its
# directory to sys.path and import the pure helper directly.
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

_SUPERSET_DIR = str(Path(__file__).resolve().parent.parent / "superset")
if _SUPERSET_DIR not in sys.path:
    sys.path.insert(0, _SUPERSET_DIR)

from bootstrap_dashboards import _probe_columns  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_db(tmp_path: Path) -> str:
    """SQLite database with empty tables mirroring the RFC 2-table schema."""
    db_path = tmp_path / "test.db"
    uri = f"sqlite:///{db_path}"
    engine = create_engine(uri)
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE test_runs (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                model_name TEXT NOT NULL,
                test_suite TEXT NOT NULL,
                total_tests INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0,
                duration_seconds REAL,
                git_commit TEXT,
                git_branch TEXT,
                hostname TEXT,
                rfc_version TEXT,
                output_xml_url TEXT,
                output_xml_source TEXT
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE test_results (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES test_runs(id),
                test_name TEXT NOT NULL,
                test_status TEXT NOT NULL,
                score INTEGER,
                tags TEXT,
                question TEXT,
                expected_answer TEXT,
                actual_answer TEXT,
                grading_reason TEXT,
                rfc_version TEXT
            )
        """)
        )
    engine.dispose()
    return uri


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProbeColumns:
    """Unit tests for _probe_columns()."""

    def test_simple_table_returns_column_names(self, empty_db: str) -> None:
        """Probing a simple SELECT on an empty table returns column names."""
        sql = "SELECT id, test_name, test_status FROM test_results"
        cols = _probe_columns(empty_db, sql)
        assert cols == ["id", "test_name", "test_status"]

    def test_join_on_empty_tables(self, empty_db: str) -> None:
        """Probing a JOIN across two empty tables still returns columns."""
        sql = """
            SELECT
                tr.id AS result_id,
                tr.test_name,
                tr.test_status,
                r.timestamp,
                r.test_suite
            FROM test_results tr
            JOIN test_runs r ON tr.run_id = r.id
        """
        cols = _probe_columns(empty_db, sql)
        assert cols == [
            "result_id",
            "test_name",
            "test_status",
            "timestamp",
            "test_suite",
        ]

    def test_aliased_expressions(self, empty_db: str) -> None:
        """Computed/CAST columns use the AS alias as column name."""
        sql = """
            SELECT
                duration_seconds,
                CAST(duration_seconds AS REAL) * 1000 AS duration_ms
            FROM test_runs
        """
        cols = _probe_columns(empty_db, sql)
        assert cols == ["duration_seconds", "duration_ms"]

    def test_aggregation_query(self, empty_db: str) -> None:
        """Aggregate queries with aliases return column names correctly."""
        sql = """
            SELECT
                hostname,
                SUM(passed) AS total_passed,
                SUM(failed) AS total_failed,
                COUNT(*) AS run_count
            FROM test_runs
            GROUP BY hostname
        """
        cols = _probe_columns(empty_db, sql)
        assert cols == ["hostname", "total_passed", "total_failed", "run_count"]

    def test_invalid_sql_raises(self, empty_db: str) -> None:
        """Bad SQL should propagate the exception (not be swallowed)."""
        with pytest.raises(Exception):
            _probe_columns(empty_db, "SELECT * FROM nonexistent_table")
