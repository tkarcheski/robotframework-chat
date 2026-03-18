"""Tests for Test Infrastructure dashboard — flaky detection & coverage.

TDD tests for the new virtual datasets, charts, layout, and filters
added to bootstrap_dashboards.py for the Test Infrastructure dashboard.
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
    _CHART_DEFS,
    _INFRA_CHART_DEFS,
    _INFRA_FILTER_CONFIGS,
    _INFRA_LAYOUT_SECTIONS,
    _VIRTUAL_DATASETS,
    _build_infra_position_json,
    _build_infra_json_metadata,
    _probe_columns,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def infra_db(tmp_path: Path) -> str:
    """SQLite DB with test_runs, test_results, and coverage_reports tables."""
    db_path = tmp_path / "infra.db"
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
                rfc_version TEXT,
                tag_severity TEXT,
                tag_tier INTEGER,
                tag_verify TEXT
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE coverage_reports (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                git_commit TEXT NOT NULL DEFAULT '',
                git_branch TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                rfc_version TEXT NOT NULL DEFAULT '',
                total_statements INTEGER NOT NULL DEFAULT 0,
                total_missed INTEGER NOT NULL DEFAULT 0,
                total_covered INTEGER NOT NULL DEFAULT 0,
                coverage_pct REAL NOT NULL DEFAULT 0.0,
                module_name TEXT NOT NULL DEFAULT '',
                module_statements INTEGER NOT NULL DEFAULT 0,
                module_missed INTEGER NOT NULL DEFAULT 0,
                module_covered INTEGER NOT NULL DEFAULT 0,
                module_coverage_pct REAL NOT NULL DEFAULT 0.0
            )
        """)
        )
    engine.dispose()
    return uri


# ---------------------------------------------------------------------------
# Flaky detection virtual datasets
# ---------------------------------------------------------------------------


class TestFlakyVirtualDatasets:
    """Tests for flaky detection SQL virtual datasets."""

    FLAKY_DATASET_KEYS = {
        "flaky_test_scores",
        "flaky_test_summary",
        "flaky_trend_timeseries",
        "kpi_flaky_test_count",
    }

    def test_flaky_datasets_present(self) -> None:
        """All flaky detection datasets exist in _VIRTUAL_DATASETS."""
        for key in self.FLAKY_DATASET_KEYS:
            assert key in _VIRTUAL_DATASETS, f"Missing flaky dataset: {key}"

    def test_flaky_sql_contains_select(self) -> None:
        """Every flaky dataset SQL contains a SELECT statement."""
        for key in self.FLAKY_DATASET_KEYS:
            sql = _VIRTUAL_DATASETS[key]
            assert "SELECT" in sql.upper(), f"{key} missing SELECT"

    def test_flaky_sql_references_test_results(self) -> None:
        """Flaky detection queries reference test_results or test_runs."""
        for key in self.FLAKY_DATASET_KEYS:
            sql_upper = _VIRTUAL_DATASETS[key].upper()
            assert "TEST_RESULTS" in sql_upper or "TEST_RUNS" in sql_upper, (
                f"{key} doesn't reference test tables"
            )

    def test_flaky_test_scores_has_expected_aliases(self) -> None:
        """flaky_test_scores SQL declares expected column aliases."""
        sql = _VIRTUAL_DATASETS["flaky_test_scores"].upper()
        assert "TEST_NAME" in sql
        assert "MODEL_NAME" in sql
        assert "FLAKY_SCORE" in sql
        assert "TOTAL_RUNS" in sql
        assert "PASS_COUNT" in sql
        assert "FAIL_COUNT" in sql

    def test_flaky_test_summary_has_expected_aliases(self) -> None:
        """flaky_test_summary SQL declares expected column aliases."""
        sql = _VIRTUAL_DATASETS["flaky_test_summary"].upper()
        assert "TEST_NAME" in sql
        assert "TOTAL_RUNS" in sql
        assert "FLAKY_SCORE" in sql

    def test_kpi_flaky_test_count_has_expected_aliases(self) -> None:
        """kpi_flaky_test_count SQL declares expected column aliases."""
        sql = _VIRTUAL_DATASETS["kpi_flaky_test_count"].upper()
        assert "FLAKY_COUNT" in sql


# ---------------------------------------------------------------------------
# Coverage virtual datasets
# ---------------------------------------------------------------------------


class TestCoverageVirtualDatasets:
    """Tests for coverage SQL virtual datasets."""

    COVERAGE_DATASET_KEYS = {
        "kpi_current_coverage",
        "coverage_timeseries",
        "coverage_by_module",
        "coverage_by_commit",
    }

    def test_coverage_datasets_present(self) -> None:
        """All coverage datasets exist in _VIRTUAL_DATASETS."""
        for key in self.COVERAGE_DATASET_KEYS:
            assert key in _VIRTUAL_DATASETS, f"Missing coverage dataset: {key}"

    def test_coverage_sql_contains_select(self) -> None:
        """Every coverage dataset SQL contains a SELECT statement."""
        for key in self.COVERAGE_DATASET_KEYS:
            sql = _VIRTUAL_DATASETS[key]
            assert "SELECT" in sql.upper(), f"{key} missing SELECT"

    def test_coverage_sql_references_coverage_reports(self) -> None:
        """Coverage queries reference the coverage_reports table."""
        for key in self.COVERAGE_DATASET_KEYS:
            sql_upper = _VIRTUAL_DATASETS[key].upper()
            assert "COVERAGE_REPORTS" in sql_upper, (
                f"{key} doesn't reference coverage_reports"
            )

    def test_kpi_current_coverage_columns(self, infra_db: str) -> None:
        """kpi_current_coverage produces expected columns."""
        sql = _VIRTUAL_DATASETS["kpi_current_coverage"]
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(infra_db, sqlite_sql)
        assert "coverage_pct" in cols

    def test_coverage_by_module_columns(self, infra_db: str) -> None:
        """coverage_by_module produces expected columns."""
        sql = _VIRTUAL_DATASETS["coverage_by_module"]
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(infra_db, sqlite_sql)
        assert "module_name" in cols
        assert "module_coverage_pct" in cols


# ---------------------------------------------------------------------------
# Infrastructure chart definitions
# ---------------------------------------------------------------------------


class TestInfraChartDefs:
    """Tests for _INFRA_CHART_DEFS list."""

    EXPECTED_CHART_NAMES = {
        # Flaky KPI row
        "Flaky Tests (7d)",
        "Flakiest Test",
        # Flaky detail
        "Flaky Test Scores",
        "Flaky Trend Over Time",
        "Flaky Tests Detail",
        # Coverage KPI row
        "Current Coverage %",
        "Coverage Delta (7d)",
        # Coverage detail
        "Coverage Over Time",
        "Coverage by Module",
        "Coverage by Commit",
    }

    def test_all_expected_charts_present(self) -> None:
        """_INFRA_CHART_DEFS contains all expected chart names."""
        chart_names = {c["slice_name"] for c in _INFRA_CHART_DEFS}
        assert self.EXPECTED_CHART_NAMES == chart_names

    def test_no_duplicate_chart_names(self) -> None:
        """No duplicate chart names in infra charts."""
        names = [c["slice_name"] for c in _INFRA_CHART_DEFS]
        assert len(names) == len(set(names))

    def test_every_chart_has_required_fields(self) -> None:
        """Every infra chart def has slice_name, viz_type, datasource_id_key, params."""
        required = {"slice_name", "viz_type", "datasource_id_key", "params"}
        for chart in _INFRA_CHART_DEFS:
            missing = required - set(chart.keys())
            assert not missing, f"{chart.get('slice_name', '?')} missing: {missing}"

    def test_chart_params_are_json_serializable(self) -> None:
        """Every infra chart's params can be serialized to JSON."""
        for chart in _INFRA_CHART_DEFS:
            try:
                json.dumps(chart["params"])
            except (TypeError, ValueError) as e:
                pytest.fail(f"{chart['slice_name']} params not JSON-serializable: {e}")

    def test_datasource_references_valid_dataset(self) -> None:
        """Every infra chart's datasource_id_key maps to a known dataset."""
        valid_datasets = {
            "test_runs",
            "test_results",
            "test_results_full",
            "coverage_reports",
        } | set(_VIRTUAL_DATASETS.keys())
        for chart in _INFRA_CHART_DEFS:
            key = chart["datasource_id_key"]
            assert key in valid_datasets, (
                f"{chart['slice_name']} references unknown dataset: {key}"
            )

    def test_no_overlap_with_health_dashboard_charts(self) -> None:
        """Infra charts don't duplicate names from the health dashboard."""
        health_names = {c["slice_name"] for c in _CHART_DEFS}
        infra_names = {c["slice_name"] for c in _INFRA_CHART_DEFS}
        overlap = health_names & infra_names
        assert not overlap, f"Chart name overlap: {overlap}"


# ---------------------------------------------------------------------------
# Infrastructure dashboard layout
# ---------------------------------------------------------------------------


class TestInfraLayout:
    """Tests for infrastructure dashboard layout."""

    def test_build_infra_position_json_returns_dict(self) -> None:
        """_build_infra_position_json returns a dict."""
        chart_id_map = {
            chart["slice_name"]: i + 100 for i, chart in enumerate(_INFRA_CHART_DEFS)
        }
        layout = _build_infra_position_json(chart_id_map)
        assert isinstance(layout, dict)

    def test_contains_root_and_grid(self) -> None:
        """Layout contains ROOT_ID and GRID_ID."""
        chart_id_map = {
            chart["slice_name"]: i + 100 for i, chart in enumerate(_INFRA_CHART_DEFS)
        }
        layout = _build_infra_position_json(chart_id_map)
        assert "ROOT_ID" in layout
        assert "GRID_ID" in layout

    def test_all_charts_have_positions(self) -> None:
        """Every infra chart has a position in the layout."""
        chart_id_map = {
            chart["slice_name"]: i + 100 for i, chart in enumerate(_INFRA_CHART_DEFS)
        }
        layout = _build_infra_position_json(chart_id_map)
        chart_ids_in_layout = set()
        for val in layout.values():
            if isinstance(val, dict) and val.get("type") == "CHART":
                chart_ids_in_layout.add(val["meta"]["chartId"])
        expected_ids = set(chart_id_map.values())
        assert expected_ids == chart_ids_in_layout

    def test_layout_is_json_serializable(self) -> None:
        """Layout can be serialized to JSON."""
        chart_id_map = {
            chart["slice_name"]: i + 100 for i, chart in enumerate(_INFRA_CHART_DEFS)
        }
        layout = _build_infra_position_json(chart_id_map)
        json.dumps(layout)  # Should not raise

    def test_layout_sections_defined(self) -> None:
        """_INFRA_LAYOUT_SECTIONS is a non-empty list."""
        assert isinstance(_INFRA_LAYOUT_SECTIONS, list)
        assert len(_INFRA_LAYOUT_SECTIONS) > 0

    def test_layout_sections_have_labels(self) -> None:
        """Every layout section has a label and charts list."""
        for section in _INFRA_LAYOUT_SECTIONS:
            assert "label" in section
            assert "charts" in section
            assert len(section["charts"]) > 0


# ---------------------------------------------------------------------------
# Infrastructure filter configuration
# ---------------------------------------------------------------------------


class TestInfraFilters:
    """Tests for _INFRA_FILTER_CONFIGS."""

    def test_has_filters(self) -> None:
        """There are native filter configurations for the infra dashboard."""
        assert len(_INFRA_FILTER_CONFIGS) >= 2

    def test_filter_names_include_time_and_model(self) -> None:
        """Filter set includes at least Time Range and Model."""
        names = {f["name"] for f in _INFRA_FILTER_CONFIGS}
        assert "Time Range" in names
        assert "Model" in names

    def test_every_filter_has_required_fields(self) -> None:
        """Every filter config has id, name, filterType, targets."""
        required = {"id", "name", "filterType", "targets"}
        for f in _INFRA_FILTER_CONFIGS:
            missing = required - set(f.keys())
            assert not missing, f"Filter {f.get('name', '?')} missing: {missing}"

    def test_filters_are_json_serializable(self) -> None:
        """Filter configs can be serialized to JSON."""
        json.dumps(_INFRA_FILTER_CONFIGS)  # Should not raise


# ---------------------------------------------------------------------------
# Infrastructure metadata builder
# ---------------------------------------------------------------------------


class TestInfraMetadata:
    """Tests for _build_infra_json_metadata."""

    def test_returns_dict_with_filters(self) -> None:
        """_build_infra_json_metadata returns dict with native_filter_configuration."""
        metadata = _build_infra_json_metadata(1, 2)
        assert isinstance(metadata, dict)
        assert "native_filter_configuration" in metadata

    def test_dataset_ids_substituted(self) -> None:
        """Placeholder dataset IDs are replaced with actual IDs."""
        metadata = _build_infra_json_metadata(42, 99)
        filters = metadata["native_filter_configuration"]
        for f in filters:
            for target in f.get("targets", []):
                ds_id = target.get("datasetId")
                if ds_id is not None:
                    assert ds_id in (42, 99), f"Unexpected dataset ID: {ds_id}"


# ---------------------------------------------------------------------------
# Coverage reports table DDL
# ---------------------------------------------------------------------------


class TestCoverageTableDDL:
    """Tests for coverage_reports table creation in _TABLE_DDL."""

    def test_coverage_reports_in_ddl(self) -> None:
        """_TABLE_DDL contains CREATE TABLE for coverage_reports."""
        from bootstrap_dashboards import _TABLE_DDL

        assert "coverage_reports" in _TABLE_DDL.lower()
        assert "create table" in _TABLE_DDL.lower()

    def test_coverage_reports_columns(self, infra_db: str) -> None:
        """coverage_reports table has all expected columns."""
        cols = _probe_columns(
            infra_db,
            "SELECT * FROM coverage_reports",
        )
        expected = {
            "id",
            "timestamp",
            "git_commit",
            "git_branch",
            "hostname",
            "rfc_version",
            "total_statements",
            "total_missed",
            "total_covered",
            "coverage_pct",
            "module_name",
            "module_statements",
            "module_missed",
            "module_covered",
            "module_coverage_pct",
        }
        assert expected == set(cols)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pg_to_sqlite(sql: str) -> str:
    """Crude adaptation of PostgreSQL SQL to SQLite for testing."""
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
    # Remove full HAVING clauses (greedy within the line context, stop at ORDER/LIMIT
    # or end of the current GROUP BY block). Match balanced content including newlines.
    sql = re.sub(
        r"HAVING\s+[^\)]*?(?=\)\s*(?:flaky|sub|sq|$)|ORDER|LIMIT|$)",
        "",
        sql,
        flags=flags,
    )
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
    # Remove ::numeric and ::text casts
    sql = re.sub(r"::\w+", "", sql, flags=flags)
    # Remove ORDER BY (not needed for column probe)
    sql = re.sub(r"ORDER\s+BY\s+.*?(?=LIMIT|\Z)", "", sql, flags=flags)
    # Remove LIMIT
    sql = re.sub(r"LIMIT\s+\d+", "", sql, flags=flags)
    # Replace NOW() with CURRENT_TIMESTAMP
    sql = re.sub(r"NOW\(\)", "CURRENT_TIMESTAMP", sql, flags=flags)
    # Replace LAG(...) OVER (...) with NULL (SQLite doesn't handle complex windows)
    sql = re.sub(
        r"LAG\s*\([^)]*\)\s*OVER\s*\([^)]*\)",
        "NULL",
        sql,
        flags=flags,
    )
    # Replace BOOL_OR/BOOL_AND with MAX/MIN
    sql = re.sub(r"BOOL_OR\s*\(", "MAX(", sql, flags=flags)
    sql = re.sub(r"BOOL_AND\s*\(", "MIN(", sql, flags=flags)
    # Remove FILTER (WHERE ...) clauses on aggregates
    sql = re.sub(
        r"FILTER\s*\(\s*WHERE\s+[^)]*\)",
        "",
        sql,
        flags=flags,
    )
    # Replace DISTINCT ON (...) with DISTINCT
    sql = re.sub(r"DISTINCT\s+ON\s*\([^)]*\)", "DISTINCT", sql, flags=flags)
    return sql
