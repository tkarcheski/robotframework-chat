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
    """SQLite database with empty tables mirroring the RFC schema."""
    db_path = tmp_path / "test.db"
    uri = f"sqlite:///{db_path}"
    engine = create_engine(uri)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE test_runs (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                model_name TEXT,
                test_suite TEXT,
                git_branch TEXT,
                git_commit TEXT,
                duration_seconds REAL,
                rfc_version TEXT,
                total_tests INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE ollama_metrics (
                id INTEGER PRIMARY KEY,
                run_id INTEGER REFERENCES test_runs(id),
                test_name TEXT,
                model_name TEXT,
                prompt_text TEXT,
                total_duration_ns INTEGER,
                load_duration_ns INTEGER,
                prompt_eval_count INTEGER,
                prompt_eval_duration_ns INTEGER,
                prompt_eval_rate REAL,
                eval_count INTEGER,
                eval_duration_ns INTEGER,
                eval_rate REAL,
                rfc_version TEXT,
                timestamp TEXT
            )
        """))
    engine.dispose()
    return uri


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProbeColumns:
    """Unit tests for _probe_columns()."""

    def test_simple_table_returns_column_names(self, empty_db: str) -> None:
        """Probing a simple SELECT on an empty table returns column names."""
        sql = "SELECT id, test_name, model_name FROM ollama_metrics"
        cols = _probe_columns(empty_db, sql)
        assert cols == ["id", "test_name", "model_name"]

    def test_join_on_empty_tables(self, empty_db: str) -> None:
        """Probing a JOIN across two empty tables still returns columns."""
        sql = """
            SELECT
                om.id AS metrics_id,
                om.test_name,
                om.model_name,
                runs.timestamp,
                runs.test_suite
            FROM ollama_metrics om
            JOIN test_runs runs ON om.run_id = runs.id
        """
        cols = _probe_columns(empty_db, sql)
        assert cols == [
            "metrics_id",
            "test_name",
            "model_name",
            "timestamp",
            "test_suite",
        ]

    def test_aliased_expressions(self, empty_db: str) -> None:
        """Computed/CAST columns use the AS alias as column name."""
        sql = """
            SELECT
                om.total_duration_ns,
                CAST(om.total_duration_ns AS REAL) / 1e9 AS total_duration_s
            FROM ollama_metrics om
        """
        cols = _probe_columns(empty_db, sql)
        assert cols == ["total_duration_ns", "total_duration_s"]

    def test_full_ollama_performance_query(self, empty_db: str) -> None:
        """The actual ollama_performance virtual dataset SQL returns all expected columns."""
        from bootstrap_dashboards import _VIRTUAL_DATASETS

        # Adapt the SQL slightly for SQLite (no DOUBLE PRECISION, use REAL)
        sql = _VIRTUAL_DATASETS["ollama_performance"].replace(
            "DOUBLE PRECISION", "REAL"
        )
        cols = _probe_columns(empty_db, sql)
        expected = [
            "metrics_id",
            "test_name",
            "model_name",
            "prompt_text",
            "total_duration_ns",
            "load_duration_ns",
            "prompt_eval_count",
            "prompt_eval_duration_ns",
            "prompt_eval_rate",
            "eval_count",
            "eval_duration_ns",
            "eval_rate",
            "rfc_version",
            "timestamp",
            "test_suite",
            "git_branch",
            "total_duration_s",
            "load_duration_s",
            "prompt_eval_duration_s",
            "eval_duration_s",
        ]
        assert cols == expected

    def test_invalid_sql_raises(self, empty_db: str) -> None:
        """Bad SQL should propagate the exception (not be swallowed)."""
        with pytest.raises(Exception):
            _probe_columns(empty_db, "SELECT * FROM nonexistent_table")
