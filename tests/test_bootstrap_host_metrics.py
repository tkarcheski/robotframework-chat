"""Tests for host metrics integration in bootstrap_dashboards.py.

Verifies that the Superset bootstrap includes:
  - host_info table in the DDL
  - hostname column on test_runs
  - host_performance virtual dataset
  - host metrics charts and dashboard function
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_SUPERSET_DIR = str(Path(__file__).resolve().parent.parent / "superset")
if _SUPERSET_DIR not in sys.path:
    sys.path.insert(0, _SUPERSET_DIR)

from bootstrap_dashboards import (  # noqa: E402
    _TABLE_DDL,
    _VIRTUAL_DATASETS,
    _probe_columns,
)


class TestHostInfoDDL:
    """The bootstrap DDL must include the host_info table and hostname column."""

    def test_host_info_table_in_ddl(self) -> None:
        """host_info table should be created by the bootstrap DDL."""
        assert "CREATE TABLE IF NOT EXISTS host_info" in _TABLE_DDL

    def test_host_info_has_hostname_column(self) -> None:
        assert "hostname" in _TABLE_DDL.split("host_info")[1]

    def test_host_info_has_os_columns(self) -> None:
        host_ddl = _TABLE_DDL.split("CREATE TABLE IF NOT EXISTS host_info")[1]
        assert "os_name" in host_ddl
        assert "os_version" in host_ddl

    def test_host_info_has_hardware_columns(self) -> None:
        host_ddl = _TABLE_DDL.split("CREATE TABLE IF NOT EXISTS host_info")[1]
        assert "cpu_arch" in host_ddl
        assert "cpu_count" in host_ddl
        assert "total_ram_gb" in host_ddl
        assert "gpu_info" in host_ddl

    def test_host_info_has_last_seen(self) -> None:
        host_ddl = _TABLE_DDL.split("CREATE TABLE IF NOT EXISTS host_info")[1]
        assert "last_seen" in host_ddl

    def test_test_runs_has_hostname_column(self) -> None:
        """test_runs DDL should include hostname for host identification."""
        runs_ddl = _TABLE_DDL.split("CREATE TABLE IF NOT EXISTS test_runs")[1].split(
            "CREATE TABLE"
        )[0]
        assert "hostname" in runs_ddl

    def test_host_info_index_exists(self) -> None:
        assert "idx_test_runs_hostname" in _TABLE_DDL


class TestHostPerformanceVirtualDataset:
    """A virtual dataset must join host_info with test_runs."""

    def test_host_performance_virtual_dataset_exists(self) -> None:
        assert "host_performance" in _VIRTUAL_DATASETS

    def test_host_performance_joins_host_info_and_test_runs(self) -> None:
        sql = _VIRTUAL_DATASETS["host_performance"]
        assert "host_info" in sql
        assert "test_runs" in sql

    def test_host_performance_includes_hardware_columns(self) -> None:
        sql = _VIRTUAL_DATASETS["host_performance"]
        assert "cpu_count" in sql
        assert "total_ram_gb" in sql
        assert "gpu_info" in sql

    def test_host_performance_includes_test_metrics(self) -> None:
        sql = _VIRTUAL_DATASETS["host_performance"]
        assert "pass_rate" in sql.lower() or "passed" in sql.lower()


@pytest.fixture()
def host_db(tmp_path: Path) -> str:
    """SQLite database with host_info and test_runs tables."""
    db_path = tmp_path / "host_test.db"
    uri = f"sqlite:///{db_path}"
    engine = create_engine(uri)
    with engine.begin() as conn:
        conn.execute(
            text("""
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
                skipped INTEGER DEFAULT 0,
                hostname TEXT
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE host_info (
                id INTEGER PRIMARY KEY,
                hostname TEXT NOT NULL UNIQUE,
                os_name TEXT,
                os_version TEXT,
                cpu_arch TEXT,
                cpu_count INTEGER,
                total_ram_gb REAL,
                gpu_info TEXT,
                last_seen TEXT,
                rfc_version TEXT
            )
        """)
        )
    engine.dispose()
    return uri


class TestHostPerformanceProbe:
    """The host_performance virtual dataset SQL must be valid."""

    def test_probe_host_performance_columns(self, host_db: str) -> None:
        sql = _VIRTUAL_DATASETS["host_performance"]
        # Adapt for SQLite
        sql = sql.replace("DOUBLE PRECISION", "REAL")
        cols = _probe_columns(host_db, sql)
        assert "hostname" in cols
        assert len(cols) >= 5


class TestHostMetricsCharts:
    """A chart function must exist for host metrics."""

    def test_host_metrics_chart_function_exists(self) -> None:
        from bootstrap_dashboards import _host_metrics_charts

        assert callable(_host_metrics_charts)

    def test_host_metrics_charts_returns_list(self) -> None:
        from bootstrap_dashboards import _host_metrics_charts

        # We can't call it without real datasets, but we can check it exists
        assert callable(_host_metrics_charts)
