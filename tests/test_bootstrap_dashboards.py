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
    _LAYOUT_SECTIONS,
    _TABLE_DDL,
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
                rfc_version TEXT,
                eval_count INTEGER,
                thinking_tokens INTEGER,
                reasoning_tokens INTEGER
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
        # Token efficiency
        "kpi_avg_tokens_per_correct",
        "model_token_efficiency",
        "token_efficiency_timeseries",
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
# Token efficiency dataset tests
# ---------------------------------------------------------------------------


class TestTokenEfficiencyDatasets:
    """Tests for the token efficiency virtual datasets."""

    TOKEN_EFFICIENCY_KEYS = {
        "kpi_avg_tokens_per_correct",
        "model_token_efficiency",
        "token_efficiency_timeseries",
    }

    def test_all_token_efficiency_keys_present(self) -> None:
        """All 3 token efficiency datasets exist in _VIRTUAL_DATASETS."""
        assert self.TOKEN_EFFICIENCY_KEYS <= set(_VIRTUAL_DATASETS.keys())

    def test_kpi_avg_tokens_columns(self, pg_like_db: str) -> None:
        """KPI avg tokens per correct SQL produces expected columns."""
        sql = _VIRTUAL_DATASETS["kpi_avg_tokens_per_correct"]
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(pg_like_db, sqlite_sql)
        assert "avg_tokens_per_correct" in cols
        assert "correct_count" in cols

    def test_model_token_efficiency_columns(self, pg_like_db: str) -> None:
        """Model token efficiency SQL produces expected columns."""
        sql = _VIRTUAL_DATASETS["model_token_efficiency"]
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(pg_like_db, sqlite_sql)
        assert "model_name" in cols
        assert "avg_tokens_per_correct" in cols
        assert "correct_count" in cols

    def test_token_efficiency_timeseries_columns(self, pg_like_db: str) -> None:
        """Token efficiency timeseries SQL produces expected columns."""
        sql = _VIRTUAL_DATASETS["token_efficiency_timeseries"]
        sqlite_sql = _pg_to_sqlite(sql)
        cols = _probe_columns(pg_like_db, sqlite_sql)
        assert "model_name" in cols
        assert "avg_tokens_per_correct" in cols

    def test_all_token_efficiency_sql_filters_correct_answers(self) -> None:
        """All token efficiency SQLs filter on score >= 0.5 and eval_count > 0."""
        for key in self.TOKEN_EFFICIENCY_KEYS:
            sql = _VIRTUAL_DATASETS[key]
            normalized = sql.upper().replace(" ", "")
            assert "SCORE>=0.5" in normalized, f"{key} missing score >= 0.5 filter"
            assert "EVAL_COUNT>0" in normalized, f"{key} missing eval_count > 0 filter"


# ---------------------------------------------------------------------------
# Token efficiency chart tests
# ---------------------------------------------------------------------------


class TestTokenEfficiencyCharts:
    """Tests for the token efficiency chart definitions."""

    TOKEN_EFFICIENCY_CHART_NAMES = {
        "Avg Tokens/Correct (24h)",
        "Model Token Efficiency",
        "Token Efficiency Trend",
    }

    def test_all_token_efficiency_charts_present(self) -> None:
        """All 3 token efficiency charts exist in _CHART_DEFS."""
        chart_names = {c["slice_name"] for c in _CHART_DEFS}
        assert self.TOKEN_EFFICIENCY_CHART_NAMES <= chart_names

    def test_kpi_chart_uses_big_number(self) -> None:
        """Avg Tokens/Correct KPI uses big_number_total viz type."""
        chart = next(
            c for c in _CHART_DEFS if c["slice_name"] == "Avg Tokens/Correct (24h)"
        )
        assert chart["viz_type"] == "big_number_total"

    def test_model_chart_uses_bar(self) -> None:
        """Model Token Efficiency uses echarts_bar viz type."""
        chart = next(
            c for c in _CHART_DEFS if c["slice_name"] == "Model Token Efficiency"
        )
        assert chart["viz_type"] == "echarts_bar"

    def test_trend_chart_uses_timeseries(self) -> None:
        """Token Efficiency Trend uses echarts_timeseries_line viz type."""
        chart = next(
            c for c in _CHART_DEFS if c["slice_name"] == "Token Efficiency Trend"
        )
        assert chart["viz_type"] == "echarts_timeseries_line"

    def test_layout_has_token_efficiency_section(self) -> None:
        """Layout sections include Token Efficiency."""
        labels = {s["label"] for s in _LAYOUT_SECTIONS}
        assert "Token Efficiency" in labels
        assert "Token Efficiency Trends" in labels


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
        # Token efficiency
        "Avg Tokens/Correct (24h)",
        "Model Token Efficiency",
        "Token Efficiency Trend",
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
        r"PERCENTILE_CONT\s*\([^)]*\)\s*WITHIN\s+GROUP\s*\(\s*ORDER\s+BY\s+([\w.]+)\s*\)",
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


class TestTableDDLSplitting:
    """Guard against SQL comments with semicolons breaking _create_tables()."""

    def test_no_comment_only_fragments_after_split(self) -> None:
        """Splitting _TABLE_DDL on ';' must not produce comment-only fragments.

        The _create_tables() function splits on ';' and executes each piece.
        A SQL comment containing a semicolon would produce a fragment that is
        non-empty but has no executable SQL, causing psycopg2 to raise
        ``ProgrammingError: can't execute an empty query``.
        """
        for i, fragment in enumerate(_TABLE_DDL.split(";")):
            # Strip comment lines and whitespace
            executable = "\n".join(
                ln
                for ln in fragment.splitlines()
                if ln.strip() and not ln.strip().startswith("--")
            ).strip()
            raw_stripped = fragment.strip()
            assert not (raw_stripped and not executable), (
                f"Fragment {i} is comment-only after ';' split — this will crash "
                f"_create_tables():\n{raw_stripped!r}"
            )


class TestResultsFullViewConsistency:
    """Guard against drift between the rfc.test_database view SQL and
    the copy embedded in superset/bootstrap_dashboards.py::_TABLE_DDL."""

    @staticmethod
    def _normalize(sql: str) -> str:
        import re

        return re.sub(r"\s+", " ", sql).strip().lower()

    def test_bootstrap_view_matches_canonical_body(self) -> None:
        from rfc.test_database import TEST_RESULTS_FULL_VIEW_BODY

        assert self._normalize(TEST_RESULTS_FULL_VIEW_BODY) in self._normalize(
            _TABLE_DDL
        ), (
            "superset/bootstrap_dashboards.py::_TABLE_DDL has drifted from "
            "rfc.test_database.TEST_RESULTS_FULL_VIEW_BODY — update both."
        )


# ---------------------------------------------------------------------------
# Agentic Stack Tracker dashboard (issue #353)
# ---------------------------------------------------------------------------

from bootstrap_dashboards import (  # noqa: E402
    _AGENTIC_CHART_DEFS,
    _AGENTIC_DATASET_TABLES,
    _AGENTIC_FILTER_CONFIGS,
    _AGENTIC_LAYOUT_SECTIONS,
    _AGENTIC_TABLE_DDL,
    _AGENTIC_VIRTUAL_DATASETS,
    _build_agentic_position_json,
)

AGENTIC_CHART_NAMES = {
    "Harness Comparison",
    "Plugin Drift",
    "Skill SHA Heatmap",
    "Token Burn Rate",
    "Outcome Funnel",
    "Latency vs Grader Score",
    "Healing Candidates This Week",
}


@pytest.fixture()
def agentic_db(tmp_path: Path) -> str:
    """SQLite database with the canonical agentic stack schema applied."""
    import sqlite3

    from rfc.harness_db import _SQLITE_SCHEMA

    db_path = tmp_path / "agentic.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SQLITE_SCHEMA)
    return f"sqlite:///{db_path}"


@pytest.fixture()
def agentic_db_with_view(agentic_db: str) -> str:
    """Agentic SQLite database with the agentic_sessions_full view created."""
    import sqlite3

    from rfc.harness_db import AGENTIC_SESSIONS_FULL_VIEW_BODY

    db_path = agentic_db.removeprefix("sqlite:///")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            f"CREATE VIEW agentic_sessions_full AS\n{AGENTIC_SESSIONS_FULL_VIEW_BODY};"
        )
    return agentic_db


class TestAgenticTableDDL:
    """Tests for the agentic stack DDL embedded in the bootstrap."""

    EXPECTED_TABLES = {
        "agentic_harnesses",
        "agentic_plugins",
        "agentic_skills",
        "agentic_metrics",
        "agentic_decisions",
        "dialog_recordings",
        "dialog_turns",
    }

    def test_creates_all_agentic_tables(self) -> None:
        for table in self.EXPECTED_TABLES:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in _AGENTIC_TABLE_DDL, (
                f"_AGENTIC_TABLE_DDL is missing table {table}"
            )

    def test_creates_sessions_full_view(self) -> None:
        assert "DROP VIEW IF EXISTS agentic_sessions_full" in _AGENTIC_TABLE_DDL
        assert "CREATE VIEW agentic_sessions_full" in _AGENTIC_TABLE_DDL

    def test_no_comment_only_fragments_after_split(self) -> None:
        """Splitting on ';' must not produce comment-only fragments."""
        for i, fragment in enumerate(_AGENTIC_TABLE_DDL.split(";")):
            executable = "\n".join(
                ln
                for ln in fragment.splitlines()
                if ln.strip() and not ln.strip().startswith("--")
            ).strip()
            raw_stripped = fragment.strip()
            assert not (raw_stripped and not executable), (
                f"Fragment {i} is comment-only after ';' split:\n{raw_stripped!r}"
            )

    def test_ddl_is_idempotent_on_sqlite(self, tmp_path: Path) -> None:
        """Running the agentic DDL twice must not error or duplicate objects.

        The DDL is written in the portable subset shared by PostgreSQL and
        SQLite (IF NOT EXISTS tables/indexes, DROP VIEW IF EXISTS + CREATE
        VIEW), so executing it twice against SQLite proves idempotency of
        the table-creation step of the bootstrap.
        """
        import sqlite3

        db_path = tmp_path / "idempotent.db"
        with sqlite3.connect(db_path) as conn:
            for _ in range(2):
                for statement in _AGENTIC_TABLE_DDL.split(";"):
                    executable = "\n".join(
                        ln
                        for ln in statement.splitlines()
                        if ln.strip() and not ln.strip().startswith("--")
                    ).strip()
                    if executable:
                        conn.execute(executable)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            views = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='view'"
                )
            }
        assert self.EXPECTED_TABLES <= tables
        assert "agentic_sessions_full" in views


class TestAgenticSessionsFullView:
    """Tests for the agentic_sessions_full view definition."""

    def test_bootstrap_view_matches_canonical_body(self) -> None:
        import re

        from rfc.harness_db import AGENTIC_SESSIONS_FULL_VIEW_BODY

        def normalize(sql: str) -> str:
            return re.sub(r"\s+", " ", sql).strip().lower()

        assert normalize(AGENTIC_SESSIONS_FULL_VIEW_BODY) in normalize(
            _AGENTIC_TABLE_DDL
        ), (
            "superset/bootstrap_dashboards.py::_AGENTIC_TABLE_DDL has drifted "
            "from rfc.harness_db.AGENTIC_SESSIONS_FULL_VIEW_BODY — update both."
        )

    def test_view_columns(self, agentic_db: str) -> None:
        from rfc.harness_db import AGENTIC_SESSIONS_FULL_VIEW_BODY

        cols = _probe_columns(agentic_db, AGENTIC_SESSIONS_FULL_VIEW_BODY)
        expected = {
            "session_id",
            "tool_name",
            "tool_version",
            "model_id",
            "rfc_version",
            "branch",
            "started_at",
            "started_ts",
            "ended_at",
            "outcome",
            "replay_of_recording_id",
            "tokens_in",
            "tokens_out",
            "avg_latency_ms",
            "avg_grader_score",
        }
        assert expected <= set(cols), f"missing: {expected - set(cols)}"

    def test_view_pivots_eav_metrics(self, agentic_db: str) -> None:
        """tokens_in/out and latency/grader pivots aggregate correctly."""
        import sqlite3

        from rfc.harness_db import AGENTIC_SESSIONS_FULL_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, tool_version, model_id, started_at) "
                "VALUES ('s1', 'claude-code', '4.7', 'claude-fable-5', "
                "'2026-06-12T00:00:00')"
            )
            rows = [
                ("m1", "s1", "tokens_in", 100.0),
                ("m2", "s1", "tokens_in", 50.0),
                ("m3", "s1", "tokens_out", 30.0),
                ("m4", "s1", "latency_ms", 200.0),
                ("m5", "s1", "latency_ms", 400.0),
                ("m6", "s1", "grader_score", 0.5),
            ]
            conn.executemany(
                "INSERT INTO agentic_metrics "
                "(id, session_id, metric_key, metric_value, recorded_at) "
                "VALUES (?, ?, ?, ?, '2026-06-12T00:00:01')",
                rows,
            )
            result = conn.execute(AGENTIC_SESSIONS_FULL_VIEW_BODY).fetchall()

        assert len(result) == 1
        row = result[0]
        # Column order matches the SELECT list probed above.
        cols = _probe_columns(agentic_db, AGENTIC_SESSIONS_FULL_VIEW_BODY)
        record = dict(zip(cols, row, strict=True))
        assert record["tokens_in"] == 150.0
        assert record["tokens_out"] == 30.0
        assert record["avg_latency_ms"] == 300.0
        assert record["avg_grader_score"] == 0.5


class TestAgenticVirtualDatasets:
    """Tests for the agentic virtual datasets."""

    EXPECTED_KEYS = {
        "agentic_plugin_drift",
        "agentic_skill_outcomes",
        "agentic_outcome_funnel",
        "agentic_healing_candidates",
    }

    def test_all_expected_keys_present(self) -> None:
        assert self.EXPECTED_KEYS <= set(_AGENTIC_VIRTUAL_DATASETS)

    def test_no_collision_with_existing_datasets(self) -> None:
        assert not set(_AGENTIC_VIRTUAL_DATASETS) & set(_VIRTUAL_DATASETS)

    def test_plugin_drift_columns(self, agentic_db: str) -> None:
        cols = _probe_columns(
            agentic_db, _AGENTIC_VIRTUAL_DATASETS["agentic_plugin_drift"]
        )
        for col in ("plugin_name", "semver", "prev_semver", "version_changed"):
            assert col in cols

    def test_skill_outcomes_columns(self, agentic_db: str) -> None:
        cols = _probe_columns(
            agentic_db, _AGENTIC_VIRTUAL_DATASETS["agentic_skill_outcomes"]
        )
        for col in ("skill_name", "outcome", "sha_changed", "session_count"):
            assert col in cols

    def test_outcome_funnel_columns(self, agentic_db: str) -> None:
        cols = _probe_columns(
            agentic_db, _AGENTIC_VIRTUAL_DATASETS["agentic_outcome_funnel"]
        )
        for col in ("tool_name", "outcome", "session_count"):
            assert col in cols

    def test_plugin_drift_flags_version_changes(self, agentic_db: str) -> None:
        """Drift dataset marks rows where semver differs from prior session."""
        import sqlite3

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at) VALUES (?, ?, ?)",
                [
                    ("s1", "claude-code", "2026-06-10T00:00:00"),
                    ("s2", "claude-code", "2026-06-11T00:00:00"),
                ],
            )
            conn.executemany(
                "INSERT INTO agentic_plugins "
                "(id, session_id, plugin_name, semver, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("p1", "s1", "anthropic", "1.0.0", "2026-06-10T00:00:01"),
                    ("p2", "s2", "anthropic", "1.1.0", "2026-06-11T00:00:01"),
                ],
            )
            rows = conn.execute(
                _AGENTIC_VIRTUAL_DATASETS["agentic_plugin_drift"]
            ).fetchall()
            cols = [
                d[0]
                for d in conn.execute(
                    _AGENTIC_VIRTUAL_DATASETS["agentic_plugin_drift"]
                ).description
            ]

        records = [dict(zip(cols, r, strict=True)) for r in rows]
        changed = [r for r in records if r["version_changed"] == 1]
        assert len(changed) == 1
        assert changed[0]["semver"] == "1.1.0"
        assert changed[0]["prev_semver"] == "1.0.0"

    def test_healing_candidates_columns(self, agentic_db: str) -> None:
        cols = _probe_columns(
            agentic_db, _AGENTIC_VIRTUAL_DATASETS["agentic_healing_candidates"]
        )
        for col in (
            "recorded_ts",
            "session_id",
            "test_name",
            "prompt_model",
            "response_text",
            "mutation_quality",
            "heal_passed",
        ):
            assert col in cols
        # raw TEXT column must not leak through: Superset needs the
        # CAST(... AS TIMESTAMP) alias for temporal filtering (PR #518)
        assert "recorded_at" not in cols

    def test_healing_candidates_filters_quality_and_outcome(
        self, agentic_db: str
    ) -> None:
        """Only heal decisions whose experiment PASSED with quality >= 0.7
        surface as candidates (issue #361)."""
        import sqlite3

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at) "
                "VALUES ('s1', 'claude-code', '2026-06-12T00:00:00')"
            )
            decisions = [
                # (id, test, action) — d1 qualifies; d2 low quality;
                # d3 experiment failed; d4 not a heal decision
                ("d1", "good test", "heal"),
                ("d2", "weak test", "heal"),
                ("d3", "failed test", "heal"),
                ("d4", "mutated test", "mutate"),
            ]
            conn.executemany(
                "INSERT INTO agentic_decisions "
                "(id, session_id, hook_event, prompt_model, prompt_text, "
                "test_name, proposed_action, applied, recorded_at) "
                "VALUES (?, 's1', 'end_test', 'm', 'p', ?, ?, 0, "
                "'2026-06-12T00:00:01')",
                decisions,
            )
            metrics = [
                ("d1", "mutation_quality", 0.9),
                ("d1-heal", "heal_passed", 1.0),
                ("d2", "mutation_quality", 0.2),
                ("d2-heal", "heal_passed", 1.0),
                ("d3", "mutation_quality", 0.9),
                ("d3-heal", "heal_passed", 0.0),
                ("d4", "mutation_quality", 0.9),
            ]
            conn.executemany(
                "INSERT INTO agentic_metrics "
                "(id, session_id, metric_key, metric_value, recorded_at) "
                "VALUES (?, 's1', ?, ?, '2026-06-12T00:00:02')",
                metrics,
            )
            rows = conn.execute(
                _AGENTIC_VIRTUAL_DATASETS["agentic_healing_candidates"]
            ).fetchall()
            cols = [
                d[0]
                for d in conn.execute(
                    _AGENTIC_VIRTUAL_DATASETS["agentic_healing_candidates"]
                ).description
            ]

        records = [dict(zip(cols, r, strict=True)) for r in rows]
        assert len(records) == 1
        assert records[0]["test_name"] == "good test"
        assert records[0]["mutation_quality"] == 0.9
        assert records[0]["heal_passed"] == 1.0


class TestAgenticChartDefs:
    """Tests for the Agentic Stack Tracker charts."""

    def test_all_expected_charts_present(self) -> None:
        names = {c["slice_name"] for c in _AGENTIC_CHART_DEFS}
        assert AGENTIC_CHART_NAMES <= names

    def test_no_duplicate_chart_names(self) -> None:
        names = [c["slice_name"] for c in _AGENTIC_CHART_DEFS]
        assert len(names) == len(set(names))

    def test_no_collision_with_existing_charts(self) -> None:
        agentic = {c["slice_name"] for c in _AGENTIC_CHART_DEFS}
        existing = {c["slice_name"] for c in _CHART_DEFS}
        assert not agentic & existing

    def test_every_chart_has_required_fields(self) -> None:
        for chart in _AGENTIC_CHART_DEFS:
            assert chart.get("slice_name")
            assert chart.get("viz_type")
            assert chart.get("datasource_id_key")
            assert isinstance(chart.get("params"), dict)

    def test_datasource_keys_reference_valid_datasets(self) -> None:
        valid = set(_AGENTIC_DATASET_TABLES) | set(_AGENTIC_VIRTUAL_DATASETS)
        for chart in _AGENTIC_CHART_DEFS:
            assert chart["datasource_id_key"] in valid, (
                f"{chart['slice_name']} references unknown dataset "
                f"{chart['datasource_id_key']}"
            )

    def test_chart_params_are_json_serializable(self) -> None:
        for chart in _AGENTIC_CHART_DEFS:
            json.dumps(chart["params"])

    def test_table_charts_have_columns(self) -> None:
        for chart in _AGENTIC_CHART_DEFS:
            if chart["viz_type"] == "table":
                assert chart["params"].get("columns"), (
                    f"{chart['slice_name']} table chart missing columns"
                )


class TestAgenticDatasetTables:
    """Physical datasets registered for the agentic dashboard."""

    def test_includes_core_tables_and_view(self) -> None:
        expected = {
            "agentic_harnesses",
            "agentic_plugins",
            "agentic_skills",
            "agentic_metrics",
            "agentic_decisions",
            "agentic_sessions_full",
        }
        assert expected <= set(_AGENTIC_DATASET_TABLES)


class TestAgenticLayout:
    """Tests for the Agentic Stack Tracker dashboard layout."""

    def test_all_charts_have_positions(self) -> None:
        layout_names = {
            spec["name"]
            for section in _AGENTIC_LAYOUT_SECTIONS
            for spec in section["charts"]
        }
        assert AGENTIC_CHART_NAMES <= layout_names

    def test_position_json_structure(self) -> None:
        chart_id_map = {
            name: i + 1 for i, name in enumerate(sorted(AGENTIC_CHART_NAMES))
        }
        layout = _build_agentic_position_json(chart_id_map)
        assert layout["ROOT_ID"]["type"] == "ROOT"
        assert layout["GRID_ID"]["type"] == "GRID"
        assert layout["HEADER_ID"]["meta"]["text"] == "Agentic Stack Tracker"
        chart_keys = [k for k in layout if k.startswith("CHART-")]
        assert len(chart_keys) == len(AGENTIC_CHART_NAMES)

    def test_position_json_is_deterministic(self) -> None:
        chart_id_map = {
            name: i + 1 for i, name in enumerate(sorted(AGENTIC_CHART_NAMES))
        }
        assert _build_agentic_position_json(chart_id_map) == (
            _build_agentic_position_json(chart_id_map)
        )

    def test_layout_is_json_serializable(self) -> None:
        chart_id_map = {
            name: i + 1 for i, name in enumerate(sorted(AGENTIC_CHART_NAMES))
        }
        json.dumps(_build_agentic_position_json(chart_id_map))


class TestAgenticFilters:
    """Tests for the agentic dashboard native filters."""

    def test_filter_names(self) -> None:
        names = {f["name"] for f in _AGENTIC_FILTER_CONFIGS}
        assert {"Tool", "Model", "RFC Version", "Outcome"} <= names

    def test_every_filter_has_required_fields(self) -> None:
        for f in _AGENTIC_FILTER_CONFIGS:
            assert f.get("id")
            assert f.get("name")
            assert f.get("filterType")
            assert f.get("targets")

    def test_select_filters_have_column_targets(self) -> None:
        for f in _AGENTIC_FILTER_CONFIGS:
            if f["filterType"] == "filter_select":
                for target in f["targets"]:
                    assert "column" in target

    def test_filters_are_json_serializable(self) -> None:
        json.dumps(_AGENTIC_FILTER_CONFIGS)
