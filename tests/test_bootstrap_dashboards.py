"""Tests for bootstrap_dashboards.py — KPI row, charts, layout, filters.

Full TDD coverage of:
- _VIRTUAL_DATASETS dict (expected keys and SQL validity)
- _probe_columns() helper
- Chart definitions (names, viz types, params)
- Dashboard layout (position_json structure)
- Native filter configuration (json_metadata)
- Color semantics and alerting cues
- STATUS_COLORS and THRESHOLD constants
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Import from bootstrap_dashboards (lives outside src/rfc/)
# ---------------------------------------------------------------------------
_SUPERSET_DIR = str(Path(__file__).resolve().parent.parent / "superset")
if _SUPERSET_DIR not in sys.path:
    sys.path.insert(0, _SUPERSET_DIR)

from bootstrap_dashboards import (  # noqa: E402
    STATUS_COLORS,
    _CHART_DEFS,
    _FILTER_CONFIGS,
    _VIRTUAL_DATASETS,
    _build_position_json,
    _probe_columns,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg_like_db(tmp_path: Path) -> str:
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
# _VIRTUAL_DATASETS tests
# ---------------------------------------------------------------------------


class TestVirtualDatasets:
    """Tests for the _VIRTUAL_DATASETS dict."""

    EXPECTED_KEYS = {
        "kpi_overall_pass_rate",
        "kpi_failing_hosts",
        "kpi_slowest_host",
        "kpi_worst_model",
        "host_pass_rate_timeseries",
        "host_current_pass_rate",
        "model_runtime_percentiles",
        "model_pass_rate_timeseries",
        "version_pass_rate",
        "host_recent_failures",
        # Flaky detection (Test Infrastructure dashboard)
        "flaky_test_scores",
        "flaky_test_summary",
        "flaky_trend_timeseries",
        "kpi_flaky_test_count",
        # Coverage (Test Infrastructure dashboard)
        "kpi_current_coverage",
        "coverage_timeseries",
        "coverage_by_module",
        "coverage_by_commit",
    }

    def test_all_expected_keys_present(self) -> None:
        """_VIRTUAL_DATASETS contains all required virtual dataset keys."""
        assert self.EXPECTED_KEYS == set(_VIRTUAL_DATASETS.keys())

    def test_all_values_are_nonempty_strings(self) -> None:
        """Every virtual dataset value is a non-empty SQL string."""
        for key, sql in _VIRTUAL_DATASETS.items():
            assert isinstance(sql, str), f"{key} is not a string"
            assert sql.strip(), f"{key} is empty"

    def test_all_sql_contains_select(self) -> None:
        """Every virtual dataset SQL contains a SELECT statement."""
        for key, sql in _VIRTUAL_DATASETS.items():
            assert "SELECT" in sql.upper(), f"{key} missing SELECT"

    def test_all_sql_references_core_tables(self) -> None:
        """Every SQL references at least one of the core tables."""
        core_tables = {"TEST_RUNS", "TEST_RESULTS", "COVERAGE_REPORTS"}
        for key, sql in _VIRTUAL_DATASETS.items():
            sql_upper = sql.upper()
            found = any(t in sql_upper for t in core_tables)
            assert found, (
                f"{key} doesn't reference test_runs, test_results, or coverage_reports"
            )

    def test_kpi_overall_pass_rate_columns(self, pg_like_db: str) -> None:
        """KPI overall pass rate SQL produces expected columns."""
        sql = _VIRTUAL_DATASETS["kpi_overall_pass_rate"]
        # Adapt PostgreSQL SQL for SQLite (remove NOW(), INTERVAL, ROUND)
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(pg_like_db, sqlite_sql)
        assert "pass_rate_pct" in cols
        assert "total_tests" in cols

    def test_host_recent_failures_columns(self, pg_like_db: str) -> None:
        """Host recent failures SQL produces expected columns."""
        sql = _VIRTUAL_DATASETS["host_recent_failures"]
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(pg_like_db, sqlite_sql)
        assert "hostname" in cols
        assert "test_name" in cols
        assert "test_status" in cols

    def test_version_pass_rate_columns(self, pg_like_db: str) -> None:
        """Version pass rate SQL produces expected columns."""
        sql = _VIRTUAL_DATASETS["version_pass_rate"]
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(pg_like_db, sqlite_sql)
        assert "rfc_version" in cols
        assert "pass_rate_pct" in cols
        assert "run_count" in cols


# ---------------------------------------------------------------------------
# _probe_columns tests
# ---------------------------------------------------------------------------


class TestProbeColumns:
    """Tests for the _probe_columns() helper."""

    def test_simple_table_returns_column_names(self, pg_like_db: str) -> None:
        """Probing a simple SELECT returns column names."""
        cols = _probe_columns(pg_like_db, "SELECT id, hostname FROM test_runs")
        assert cols == ["id", "hostname"]

    def test_join_returns_aliased_columns(self, pg_like_db: str) -> None:
        """Probing a JOIN with aliases returns alias names."""
        sql = """
            SELECT
                tr.test_name,
                r.hostname,
                r.model_name
            FROM test_results tr
            JOIN test_runs r ON tr.run_id = r.id
        """
        cols = _probe_columns(pg_like_db, sql)
        assert cols == ["test_name", "hostname", "model_name"]

    def test_computed_column_uses_alias(self, pg_like_db: str) -> None:
        """Computed expressions use the AS alias as column name."""
        sql = """
            SELECT
                hostname,
                CAST(passed AS REAL) / MAX(total_tests, 1) AS pass_rate
            FROM test_runs
        """
        cols = _probe_columns(pg_like_db, sql)
        assert "pass_rate" in cols

    def test_invalid_sql_raises(self, pg_like_db: str) -> None:
        """Bad SQL raises an exception."""
        with pytest.raises(Exception):
            _probe_columns(pg_like_db, "SELECT * FROM nonexistent_xyz")


# ---------------------------------------------------------------------------
# Chart definitions tests
# ---------------------------------------------------------------------------


class TestChartDefs:
    """Tests for the _CHART_DEFS list."""

    # All expected chart names in the consolidated dashboard
    EXPECTED_CHART_NAMES = {
        # KPI row
        "Overall Pass Rate (24h)",
        "Failing Hosts",
        "Slowest Host",
        "Worst Model Today",
        # Host health
        "Host Pass Rate Over Time",
        "Current Pass Rate by Host",
        "Recent Failures by Host",
        # Model performance
        "Pass Trends by Model",
        "Model Runtime Distribution",
        "Model Comparison — Pass Rate",
        # Git/version
        "RFC Version Distribution",
        "Pass Rate by RFC Version",
        # Status
        "Test Status Breakdown",
        # Drill-down
        "Recent Test Runs",
        "Test Results Detail",
    }

    def test_all_expected_charts_present(self) -> None:
        """_CHART_DEFS contains all expected chart names."""
        chart_names = {c["slice_name"] for c in _CHART_DEFS}
        assert self.EXPECTED_CHART_NAMES == chart_names

    def test_no_duplicate_chart_names(self) -> None:
        """No duplicate chart names."""
        names = [c["slice_name"] for c in _CHART_DEFS]
        assert len(names) == len(set(names))

    def test_every_chart_has_required_fields(self) -> None:
        """Every chart def has slice_name, viz_type, datasource_id_key, params."""
        required = {"slice_name", "viz_type", "datasource_id_key", "params"}
        for chart in _CHART_DEFS:
            missing = required - set(chart.keys())
            assert not missing, f"{chart.get('slice_name', '?')} missing: {missing}"

    def test_kpi_charts_use_big_number(self) -> None:
        """KPI charts use big_number_total viz type."""
        kpi_names = {
            "Overall Pass Rate (24h)",
            "Failing Hosts",
            "Slowest Host",
            "Worst Model Today",
        }
        for chart in _CHART_DEFS:
            if chart["slice_name"] in kpi_names:
                assert chart["viz_type"] == "big_number_total", (
                    f"{chart['slice_name']} should be big_number_total"
                )

    def test_timeseries_charts_have_time_column(self) -> None:
        """All timeseries charts have a time_column or x_axis in params."""
        for chart in _CHART_DEFS:
            if "timeseries" in chart["viz_type"]:
                params = chart["params"]
                has_time = (
                    "time_column" in params
                    or "x_axis" in params
                    or "granularity_sqla" in params
                )
                assert has_time, f"{chart['slice_name']} timeseries missing time config"

    def test_bar_charts_have_groupby(self) -> None:
        """All bar charts have a groupby in params."""
        for chart in _CHART_DEFS:
            if chart["viz_type"] == "echarts_bar":
                assert "groupby" in chart["params"], (
                    f"{chart['slice_name']} bar chart missing groupby"
                )

    def test_table_charts_have_columns(self) -> None:
        """All table charts have columns in params."""
        for chart in _CHART_DEFS:
            if chart["viz_type"] == "table":
                params = chart["params"]
                has_cols = "columns" in params or "all_columns" in params
                assert has_cols, f"{chart['slice_name']} table missing columns"

    def test_datasource_id_key_references_valid_dataset(self) -> None:
        """Every chart's datasource_id_key maps to a known dataset name."""
        valid_datasets = {
            "test_runs",
            "test_results",
            "test_results_full",
        } | set(_VIRTUAL_DATASETS.keys())
        for chart in _CHART_DEFS:
            key = chart["datasource_id_key"]
            assert key in valid_datasets, (
                f"{chart['slice_name']} references unknown dataset: {key}"
            )

    def test_chart_params_are_json_serializable(self) -> None:
        """Every chart's params can be serialized to JSON."""
        for chart in _CHART_DEFS:
            try:
                json.dumps(chart["params"])
            except (TypeError, ValueError) as e:
                pytest.fail(f"{chart['slice_name']} params not JSON-serializable: {e}")


# ---------------------------------------------------------------------------
# Dashboard layout tests
# ---------------------------------------------------------------------------


class TestDashboardLayout:
    """Tests for _build_position_json() output."""

    def test_returns_dict(self) -> None:
        """_build_position_json returns a dict."""
        # Use placeholder chart IDs for testing
        chart_id_map = {
            chart["slice_name"]: i + 1 for i, chart in enumerate(_CHART_DEFS)
        }
        layout = _build_position_json(chart_id_map)
        assert isinstance(layout, dict)

    def test_contains_root_and_grid(self) -> None:
        """Layout contains ROOT_ID and GRID_ID."""
        chart_id_map = {
            chart["slice_name"]: i + 1 for i, chart in enumerate(_CHART_DEFS)
        }
        layout = _build_position_json(chart_id_map)
        assert "ROOT_ID" in layout
        assert "GRID_ID" in layout

    def test_all_charts_have_positions(self) -> None:
        """Every chart in _CHART_DEFS has a position in the layout."""
        chart_id_map = {
            chart["slice_name"]: i + 1 for i, chart in enumerate(_CHART_DEFS)
        }
        layout = _build_position_json(chart_id_map)
        chart_ids_in_layout = set()
        for key, val in layout.items():
            if isinstance(val, dict) and val.get("type") == "CHART":
                chart_ids_in_layout.add(val["meta"]["chartId"])
        expected_ids = set(chart_id_map.values())
        assert expected_ids == chart_ids_in_layout

    def test_kpi_row_is_first(self) -> None:
        """KPI charts appear in the first row of the layout."""
        chart_id_map = {
            chart["slice_name"]: i + 1 for i, chart in enumerate(_CHART_DEFS)
        }
        layout = _build_position_json(chart_id_map)
        # Find the first ROW in the GRID's children
        grid = layout["GRID_ID"]
        first_row_id = grid["children"][0]
        first_row = layout[first_row_id]
        # Check that it contains KPI chart references
        kpi_names = {
            "Overall Pass Rate (24h)",
            "Failing Hosts",
            "Slowest Host",
            "Worst Model Today",
        }
        kpi_ids = {chart_id_map[name] for name in kpi_names}
        row_chart_ids = set()
        for child_id in first_row["children"]:
            child = layout[child_id]
            if child.get("type") == "CHART":
                row_chart_ids.add(child["meta"]["chartId"])
        assert kpi_ids == row_chart_ids

    def test_layout_is_json_serializable(self) -> None:
        """Layout can be serialized to JSON."""
        chart_id_map = {
            chart["slice_name"]: i + 1 for i, chart in enumerate(_CHART_DEFS)
        }
        layout = _build_position_json(chart_id_map)
        json.dumps(layout)  # Should not raise


# ---------------------------------------------------------------------------
# Filter configuration tests
# ---------------------------------------------------------------------------


class TestFilterConfigs:
    """Tests for _FILTER_CONFIGS."""

    def test_has_four_filters(self) -> None:
        """There are exactly 4 native filter configurations."""
        assert len(_FILTER_CONFIGS) == 4

    def test_filter_names(self) -> None:
        """Filter names match expected set."""
        names = {f["name"] for f in _FILTER_CONFIGS}
        assert names == {"Time Range", "Host", "Model", "RFC Version"}

    def test_every_filter_has_required_fields(self) -> None:
        """Every filter config has id, name, filterType, targets."""
        required = {"id", "name", "filterType", "targets"}
        for f in _FILTER_CONFIGS:
            missing = required - set(f.keys())
            assert not missing, f"Filter {f.get('name', '?')} missing: {missing}"

    def test_time_filter_is_time_type(self) -> None:
        """Time Range filter uses filter_time type."""
        time_filters = [f for f in _FILTER_CONFIGS if f["name"] == "Time Range"]
        assert len(time_filters) == 1
        assert time_filters[0]["filterType"] == "filter_time"

    def test_select_filters_have_column_targets(self) -> None:
        """Select filters (Host, Model, RFC Version) target specific columns."""
        expected_columns = {
            "Host": "hostname",
            "Model": "model_name",
            "RFC Version": "rfc_version",
        }
        for f in _FILTER_CONFIGS:
            if f["name"] in expected_columns:
                assert f["filterType"] == "filter_select"
                target = f["targets"][0]
                assert target["column"]["name"] == expected_columns[f["name"]]

    def test_filters_are_json_serializable(self) -> None:
        """Filter configs can be serialized to JSON."""
        json.dumps(_FILTER_CONFIGS)  # Should not raise


# ---------------------------------------------------------------------------
# Color semantics tests
# ---------------------------------------------------------------------------


class TestColorSemantics:
    """Tests for STATUS_COLORS and visual alerting constants."""

    def test_status_colors_has_pass_fail_skip(self) -> None:
        """STATUS_COLORS defines colors for PASS, FAIL, ERROR, SKIP."""
        assert "PASS" in STATUS_COLORS
        assert "FAIL" in STATUS_COLORS
        assert "ERROR" in STATUS_COLORS
        assert "SKIP" in STATUS_COLORS

    def test_pass_is_green(self) -> None:
        """PASS color is green-ish."""
        color = STATUS_COLORS["PASS"].lower()
        # Green hex starts with #2 or #3 or contains "green"
        assert color.startswith("#2") or color.startswith("#3") or "green" in color

    def test_fail_is_red(self) -> None:
        """FAIL color is red-ish."""
        color = STATUS_COLORS["FAIL"].lower()
        assert color.startswith("#e") or color.startswith("#f") or "red" in color

    def test_colors_are_valid_hex(self) -> None:
        """All status colors are valid hex color strings."""
        for status, color in STATUS_COLORS.items():
            assert color.startswith("#"), f"{status} color missing #: {color}"
            assert len(color) == 7, f"{status} color wrong length: {color}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pg_to_sqlite(sql: str) -> str:
    """Crude adaptation of PostgreSQL SQL to SQLite for testing.

    Strips PostgreSQL-specific syntax so _probe_columns can run on SQLite.
    Not meant to produce correct results — just valid column names.
    Uses re.DOTALL so \\s+ spans newlines.
    """
    import re

    flags = re.IGNORECASE | re.DOTALL

    # Remove WHERE ... >= NOW() - INTERVAL '...'
    sql = re.sub(
        r"WHERE\s+(?:\w+\.)?timestamp\s*>=\s*NOW\(\)\s*-\s*INTERVAL\s*'[^']*'",
        "WHERE 1=1",
        sql,
        flags=flags,
    )
    # Remove AND ... >= NOW() - INTERVAL '...'
    sql = re.sub(
        r"AND\s+(?:\w+\.)?timestamp\s*>=\s*NOW\(\)\s*-\s*INTERVAL\s*'[^']*'",
        "",
        sql,
        flags=flags,
    )
    # Remove HAVING clauses
    sql = re.sub(r"HAVING\s+.*?(?=ORDER|LIMIT|GROUP|\Z)", "", sql, flags=flags)
    # Replace DATE_TRUNC('...', col) with col
    sql = re.sub(
        r"DATE_TRUNC\s*\(\s*'[^']*'\s*,\s*(\w+(?:\.\w+)?)\s*\)",
        r"\1",
        sql,
        flags=flags,
    )
    # Replace PERCENTILE_CONT(...) WITHIN GROUP (ORDER BY col) with AVG(col)
    sql = re.sub(
        r"PERCENTILE_CONT\s*\([^)]*\)\s*WITHIN\s+GROUP\s*\(\s*ORDER\s+BY\s+(\w+)\s*\)",
        r"AVG(\1)",
        sql,
        flags=flags,
    )
    # Remove ::numeric casts
    sql = re.sub(r"::numeric", "", sql, flags=flags)
    # Remove ORDER BY (not needed for column probe)
    sql = re.sub(r"ORDER\s+BY\s+.*?(?=LIMIT|\Z)", "", sql, flags=flags)
    # Remove LIMIT
    sql = re.sub(r"LIMIT\s+\d+", "", sql, flags=flags)
    # Replace NOW() with CURRENT_TIMESTAMP for any remaining occurrences
    sql = re.sub(r"NOW\(\)", "CURRENT_TIMESTAMP", sql, flags=flags)
    # Replace IN ('FAIL', 'ERROR') — SQLite supports this, so leave it
    return sql
