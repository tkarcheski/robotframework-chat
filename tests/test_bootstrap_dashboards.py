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
import os
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
    _agentic_dataset_is_current,
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


def _exec_agentic_ddl_sqlite(conn: "object", ddl: str) -> None:
    """Execute the bootstrap DDL on a SQLite connection, per _run_ddl semantics.

    Mirrors ``bootstrap_dashboards._run_ddl``: split on ';', strip comment lines,
    skip empty fragments. One SQLite-only translation: PostgreSQL (the production
    ``_run_ddl`` target) supports ``ADD COLUMN IF NOT EXISTS`` natively, SQLite
    does not — so those upgrade-path ALTERs (#660) are rewritten without the
    clause and a duplicate-column error is treated as the idempotent no-op, the
    same idiom the spine migrations use (rfc.harness_db._SQLITE_MIGRATIONS).
    """
    import re
    import sqlite3

    for statement in ddl.split(";"):
        executable = "\n".join(
            ln
            for ln in statement.splitlines()
            if ln.strip() and not ln.strip().startswith("--")
        ).strip()
        if not executable:
            continue
        add_col = re.match(
            r"ALTER TABLE\s+\S+\s+ADD COLUMN IF NOT EXISTS\b",
            executable,
            re.IGNORECASE,
        )
        if add_col:
            try:
                conn.execute(  # type: ignore[attr-defined]
                    executable.replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN")
                )
            except sqlite3.OperationalError:
                pass  # idempotent: column already present
        else:
            conn.execute(executable)  # type: ignore[attr-defined]


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
        VIEW) with ONE PostgreSQL-only construct — the #660 upgrade ALTERs'
        ``ADD COLUMN IF NOT EXISTS``, which ``_exec_agentic_ddl_sqlite``
        emulates — so executing it twice against SQLite proves idempotency of
        the table-creation step of the bootstrap.
        """
        import sqlite3

        db_path = tmp_path / "idempotent.db"
        with sqlite3.connect(db_path) as conn:
            for _ in range(2):
                _exec_agentic_ddl_sqlite(conn, _AGENTIC_TABLE_DDL)
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

    def test_ddl_upgrades_pre_existing_lean_table(self, tmp_path: Path) -> None:
        """The bootstrap DDL upgrades an OLD-shape agentic_harnesses in place.

        Codex finding (mirror PR #660, fixed at source in #374): on an existing
        database ``CREATE TABLE IF NOT EXISTS`` is a no-op, so the columns the
        scoreboard view references but the original lean table never had
        (``scenario_id`` #347, ``verified_local`` #350) stayed missing and the
        ``CREATE VIEW`` crashed with a missing-column error. The DDL's additive
        ALTERs must bring the old table up to the view's surface — and running
        the DDL again must stay idempotent.
        """
        import sqlite3

        db_path = tmp_path / "upgrade.db"
        with sqlite3.connect(db_path) as conn:
            # The ORIGINAL lean bootstrap shape: no scenario_id, no verified_local.
            conn.execute(
                """
                CREATE TABLE agentic_harnesses (
                    session_id              TEXT PRIMARY KEY,
                    tool_name               TEXT NOT NULL,
                    tool_version            TEXT,
                    model_id                TEXT,
                    rfc_version             TEXT,
                    branch                  TEXT,
                    started_at              TEXT NOT NULL,
                    ended_at                TEXT,
                    outcome                 TEXT,
                    replay_of_recording_id  TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO agentic_harnesses (session_id, tool_name, started_at) "
                "VALUES ('old-row', 'opencode', '2026-07-14T00:00:00')"
            )
            for _ in range(2):  # upgrade + idempotent re-run
                _exec_agentic_ddl_sqlite(conn, _AGENTIC_TABLE_DDL)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
            views = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='view'"
                )
            }
            # Pre-existing row survived the additive upgrade, no data rewrite.
            survivors = conn.execute(
                "SELECT session_id, scenario_id, verified_local FROM agentic_harnesses"
            ).fetchall()
        assert {"scenario_id", "verified_local"} <= cols
        assert "harness_scoreboard" in views  # the view creates cleanly post-upgrade
        assert survivors == [("old-row", None, None)]  # NULL, fail-closed Tier B


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
            "cache_hit_rate",
            "suite_runtime_ms",
            # RFC-012 MS5 (#328): open-tolkein route-efficiency pivots.
            "route_taken",
            "tokens_saved_by_route",
            "route_local_fraction",
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
                # RFC-010 S1 (#258): cache_hit_rate AVG'd, suite_runtime_ms SUM'd
                ("m7", "s1", "cache_hit_rate", 0.5),
                ("m8", "s1", "cache_hit_rate", 1.0),
                ("m9", "s1", "suite_runtime_ms", 1000.0),
                ("m10", "s1", "suite_runtime_ms", 500.0),
                # RFC-012 MS5 (#328): route_taken/route_local_fraction AVG'd,
                # tokens_saved_by_route SUM'd (the headline "LOTR-books" total).
                ("m11", "s1", "route_taken", 1.0),
                ("m12", "s1", "route_taken", 3.0),
                ("m13", "s1", "tokens_saved_by_route", 800.0),
                ("m14", "s1", "tokens_saved_by_route", 200.0),
                ("m15", "s1", "route_local_fraction", 1.0),
                ("m16", "s1", "route_local_fraction", 0.0),
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
        assert record["cache_hit_rate"] == 0.75  # AVG(0.5, 1.0)
        assert record["suite_runtime_ms"] == 1500.0  # SUM(1000, 500)
        assert record["route_taken"] == 2.0  # AVG(1, 3): mean route depth
        assert record["tokens_saved_by_route"] == 1000.0  # SUM(800, 200)
        assert record["route_local_fraction"] == 0.5  # AVG(1.0, 0.0)


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


class TestAgenticDatasetIsCurrent:
    """A dataset is current only when its SQL matches AND its stored columns
    include rfc_version — fetch_metadata can fail independently of the SQL
    commit, leaving rfc_version missing and the native filter broken (#508)."""

    SQL = "SELECT rfc_version, tool_name FROM agentic_harnesses"

    def test_sql_match_with_rfc_version_is_current(self) -> None:
        assert _agentic_dataset_is_current(
            self.SQL, ["rfc_version", "tool_name"], self.SQL
        )

    def test_sql_match_but_missing_rfc_version_needs_refresh(self) -> None:
        # The bug: prior fetch_metadata failed, columns lack rfc_version, but
        # SQL matches — must NOT be treated as current.
        assert not _agentic_dataset_is_current(self.SQL, ["tool_name"], self.SQL)

    def test_empty_columns_needs_refresh(self) -> None:
        assert not _agentic_dataset_is_current(self.SQL, [], self.SQL)

    def test_sql_differs_needs_refresh(self) -> None:
        assert not _agentic_dataset_is_current("SELECT 1", ["rfc_version"], self.SQL)

    def test_whitespace_only_sql_difference_is_current(self) -> None:
        assert _agentic_dataset_is_current(self.SQL + "  \n", ["rfc_version"], self.SQL)

    def test_none_stored_sql_needs_refresh(self) -> None:
        assert not _agentic_dataset_is_current(None, ["rfc_version"], self.SQL)


class TestPluginDriftPartitionsByTool:
    """Interleaved tools at stable versions must show zero drift (#484)."""

    def test_interleaved_tools_no_false_version_changes(self, agentic_db: str) -> None:
        import sqlite3

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at) VALUES (?, ?, ?)",
                [
                    ("c1", "claude-code", "2026-06-10T00:00:00"),
                    ("x1", "codex", "2026-06-10T01:00:00"),
                    ("c2", "claude-code", "2026-06-10T02:00:00"),
                    ("x2", "codex", "2026-06-10T03:00:00"),
                ],
            )
            # Same plugin, per-tool versions are individually STABLE.
            conn.executemany(
                "INSERT INTO agentic_plugins "
                "(id, session_id, plugin_name, semver, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("p1", "c1", "anthropic", "1.0.0", "2026-06-10T00:00:01"),
                    ("p2", "x1", "anthropic", "2.0.0", "2026-06-10T01:00:01"),
                    ("p3", "c2", "anthropic", "1.0.0", "2026-06-10T02:00:01"),
                    ("p4", "x2", "anthropic", "2.0.0", "2026-06-10T03:00:01"),
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
            records = [dict(zip(cols, r)) for r in rows]
            changed = [r for r in records if r["version_changed"] == 1]
            assert changed == [], (
                "stable per-tool versions must not be flagged as drift when "
                "sessions from different tools interleave"
            )


# ---------------------------------------------------------------------------
# Harness Scoreboard view + dashboard (RFC-007 S5 / issue #221)
# ---------------------------------------------------------------------------

from bootstrap_dashboards import (  # noqa: E402
    _SCOREBOARD_CHART_DEFS,
    _SCOREBOARD_FILTER_CONFIGS,
    _SCOREBOARD_LAYOUT_SECTIONS,
    _build_scoreboard_position_json,
)

SCOREBOARD_CHART_NAMES = {
    "Harness Pass Rate",
    "Harness Scoreboard",
    "Harness Economy",
    "Harness Token Efficiency",
    "Harness Runtime & Latency",
    "Harness Cache Hit Rate",
}

# Column order matches the HARNESS_SCOREBOARD_VIEW_BODY SELECT list.
SCOREBOARD_COLUMNS = {
    "tool_name",
    "model_id",
    "scenario_id",
    "tier",
    "cell_label",
    "run_count",
    "pass_count",
    "pass_rate",
    "avg_churn_ratio",
    "avg_process_violations",
    "avg_tokens_in",
    "avg_tokens_out",
    "avg_latency_ms",
    "avg_cache_hit_rate",
    "avg_suite_runtime_ms",
    # RFC-012 MS5 (#328): open-tolkein route-efficiency per-cell means.
    "avg_route_taken",
    "avg_tokens_saved_by_route",
    "avg_route_local_fraction",
}


def _insert_run(
    conn: "object",
    *,
    session_id: str,
    tool_name: str,
    model_id: str,
    scenario_id: str | None,
    metrics: dict[str, float],
    verified_local: int | None = None,
) -> None:
    """Seed one harness run + its EAV metric rows on an agentic SQLite DB.

    ``verified_local`` is the #350 persisted local-resolution verdict the
    scoreboard view derives ``tier`` from: 1 -> Tier A, 0/NULL -> Tier B. It
    defaults to NULL (fail-closed to Tier B) so a run only ever reaches Tier A by
    explicitly carrying the verdict a minted token would have written.
    """
    conn.execute(  # type: ignore[attr-defined]
        "INSERT INTO agentic_harnesses "
        "(session_id, tool_name, model_id, scenario_id, verified_local, started_at) "
        "VALUES (?, ?, ?, ?, ?, '2026-07-14T00:00:00')",
        (session_id, tool_name, model_id, scenario_id, verified_local),
    )
    conn.executemany(  # type: ignore[attr-defined]
        "INSERT INTO agentic_metrics "
        "(id, session_id, metric_key, metric_value, recorded_at) "
        "VALUES (?, ?, ?, ?, '2026-07-14T00:00:01')",
        [
            (f"{session_id}-{key}", session_id, key, value)
            for key, value in metrics.items()
        ],
    )


class TestHarnessScoreboardDDL:
    """The scoreboard view is embedded in the bootstrap and drift-guarded."""

    def test_bootstrap_ddl_creates_scoreboard_view(self) -> None:
        assert "DROP VIEW IF EXISTS harness_scoreboard" in _AGENTIC_TABLE_DDL
        assert "CREATE VIEW harness_scoreboard" in _AGENTIC_TABLE_DDL

    def test_bootstrap_view_matches_canonical_body(self) -> None:
        """The embedded copy must not drift from the canonical view body."""
        import re

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        def normalize(sql: str) -> str:
            return re.sub(r"\s+", " ", sql).strip().lower()

        assert normalize(HARNESS_SCOREBOARD_VIEW_BODY) in normalize(
            _AGENTIC_TABLE_DDL
        ), (
            "superset/bootstrap_dashboards.py::_AGENTIC_TABLE_DDL has drifted "
            "from rfc.harness_db.HARNESS_SCOREBOARD_VIEW_BODY — update both."
        )

    def test_full_ddl_creates_view_on_sqlite(self, tmp_path: Path) -> None:
        """The whole _AGENTIC_TABLE_DDL (lean base table + view) runs on SQLite.

        Proves the scoreboard view's grouping column (``scenario_id``) is present
        in the bootstrap's own base table, so the embedded view is executable
        standalone (not only against the migrated canonical schema).
        """
        import sqlite3

        db_path = tmp_path / "scoreboard_ddl.db"
        with sqlite3.connect(db_path) as conn:
            _exec_agentic_ddl_sqlite(conn, _AGENTIC_TABLE_DDL)
            views = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='view'"
                )
            }
        assert "harness_scoreboard" in views


class TestHarnessScoreboardView:
    """Aggregate math + tier-separation honesty of the scoreboard view."""

    def test_view_columns(self, agentic_db: str) -> None:
        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
        assert SCOREBOARD_COLUMNS <= set(cols), (
            f"missing: {SCOREBOARD_COLUMNS - set(cols)}"
        )

    def test_cell_math_known_answer(self, agentic_db: str) -> None:
        """Per-cell aggregates over seeded runs match hand-computed values."""
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            # opencode (Tier A) — two runs at the same scenario, one pass one fail.
            # verified_local=1: both minted the local-resolution token (#350).
            _insert_run(
                conn,
                session_id="o1",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id="s_bugfix",
                verified_local=1,
                metrics={
                    "task_success": 1.0,
                    "churn_ratio": 1.0,
                    "process_violations": 0.0,
                    "tokens_in": 100.0,
                    "tokens_out": 50.0,
                    "latency_ms": 200.0,
                    "cache_hit_rate": 0.5,
                    "suite_runtime_ms": 1000.0,
                    "route_taken": 1.0,
                    "tokens_saved_by_route": 800.0,
                    "route_local_fraction": 1.0,
                },
            )
            _insert_run(
                conn,
                session_id="o2",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id="s_bugfix",
                verified_local=1,
                metrics={
                    "task_success": 0.0,
                    "churn_ratio": 3.0,
                    "process_violations": 2.0,
                    "tokens_in": 200.0,
                    "tokens_out": 150.0,
                    "latency_ms": 400.0,
                    "cache_hit_rate": 1.0,
                    "suite_runtime_ms": 2000.0,
                    "route_taken": 3.0,
                    "tokens_saved_by_route": 200.0,
                    "route_local_fraction": 0.0,
                },
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()

        records = {
            (r["tool_name"], r["scenario_id"]): r
            for r in (dict(zip(cols, row, strict=True)) for row in rows)
        }
        cell = records[("opencode", "s_bugfix")]
        assert cell["tier"] == "A"
        assert cell["cell_label"] == "[A] opencode @ qwen-local"
        assert cell["run_count"] == 2
        assert cell["pass_count"] == 1.0
        assert cell["pass_rate"] == 0.5
        assert cell["avg_churn_ratio"] == 2.0
        assert cell["avg_process_violations"] == 1.0
        assert cell["avg_tokens_in"] == 150.0
        assert cell["avg_tokens_out"] == 100.0
        assert cell["avg_latency_ms"] == 300.0
        assert cell["avg_cache_hit_rate"] == 0.75
        assert cell["avg_suite_runtime_ms"] == 1500.0
        assert cell["avg_route_taken"] == 2.0  # AVG(1, 3): mean route depth
        assert cell["avg_tokens_saved_by_route"] == 500.0  # AVG(800, 200)
        assert cell["avg_route_local_fraction"] == 0.5  # AVG(1.0, 0.0)

    def test_tier_separation_never_shares_a_cell(self, agentic_db: str) -> None:
        """A Tier-B native run never lands in a Tier-A cell (RFC-007 s5 / #273).

        Same scenario, one opencode (Tier A) pass and one claude-code (Tier B)
        pass. The two MUST be separate rows with distinct tiers/labels, and the
        Tier-A cell's pass_rate must be untouched by the Tier-B result.
        """
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            _insert_run(
                conn,
                session_id="a1",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id="s_shared",
                verified_local=1,  # minted the local-resolution token -> Tier A
                metrics={"task_success": 0.0},  # Tier-A FAILED
            )
            _insert_run(
                conn,
                session_id="b1",
                tool_name="claude-code",
                model_id="claude-fable-5",
                scenario_id="s_shared",
                verified_local=0,  # native, no token -> Tier B
                metrics={"task_success": 1.0},  # Tier-B PASSED
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()

        records = [dict(zip(cols, row, strict=True)) for row in rows]
        by_tool = {r["tool_name"]: r for r in records}
        # Two distinct cells for the one scenario — never merged.
        assert len(records) == 2
        assert by_tool["opencode"]["tier"] == "A"
        assert by_tool["claude-code"]["tier"] == "B"
        # The Tier-A cell is a clean 0.0 — the Tier-B pass never leaks in.
        assert by_tool["opencode"]["pass_rate"] == 0.0
        assert by_tool["claude-code"]["pass_rate"] == 1.0
        # Labels are structurally distinct, so a heatmap can never overlay them.
        assert by_tool["opencode"]["cell_label"].startswith("[A] ")
        assert by_tool["claude-code"]["cell_label"].startswith("[B] ")

    def test_tier_is_the_persisted_token_not_the_tool_name(
        self, agentic_db: str
    ) -> None:
        """The view's tier follows the persisted ``verified_local`` verdict, not the
        tool_name allowlist — the #350 fix, with the exact lie it documents killed.

        Pre-#350 the view read ``CASE WHEN tool_name IN ('opencode','codex')``, so a
        misconfigured remote run under one of those NAMES was promoted to a green
        Tier-A cell even though it never resolved local (the #273 lie). Now the tier
        is derived FAIL-CLOSED from the token verdict the write path persisted:

          * the SAME tool_name 'opencode' lands Tier A when it minted the token
            (verified_local=1) and Tier B when it did not (a remote-pointed run) —
            proving the name is no longer what promotes;
          * an allowlist name ('codex') without the token is Tier B, not Tier A;
          * an unknown harness with no verdict (NULL) fails closed to Tier B.
        """
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            # opencode that actually pinned local -> token minted -> Tier A.
            _insert_run(
                conn,
                session_id="o_local",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id="s_bugfix",
                verified_local=1,
                metrics={"task_success": 1.0},
            )
            # opencode misconfigured at a REMOTE provider -> no token -> Tier B.
            # THIS is the #350 lie: pre-fix the 'opencode' name alone made it A.
            _insert_run(
                conn,
                session_id="o_remote",
                tool_name="opencode",
                model_id="remote-gpt",
                scenario_id="s_bugfix",
                verified_local=0,
                metrics={"task_success": 1.0},
            )
            # codex WITH the token -> Tier A (affirmatively fixed-local).
            _insert_run(
                conn,
                session_id="x_local",
                tool_name="codex",
                model_id="qwen-local",
                scenario_id="s_bugfix",
                verified_local=1,
                metrics={"task_success": 1.0},
            )
            # codex WITHOUT the token -> Tier B (the allowlist name no longer saves it).
            _insert_run(
                conn,
                session_id="x_remote",
                tool_name="codex",
                model_id="remote-gpt",
                scenario_id="s_bugfix",
                verified_local=0,
                metrics={"task_success": 1.0},
            )
            # An unknown harness with no verdict (NULL) fails closed to Tier B.
            _insert_run(
                conn,
                session_id="m1",
                tool_name="mystery-agent",
                model_id="who-knows",
                scenario_id="s_bugfix",
                verified_local=None,
                metrics={"task_success": 1.0},
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()

        by_cell = {
            (r["tool_name"], r["model_id"]): r
            for r in (dict(zip(cols, row, strict=True)) for row in rows)
        }
        # Same 'opencode' name, opposite tiers — the token decides, not the name.
        assert by_cell[("opencode", "qwen-local")]["tier"] == "A"
        assert by_cell[("opencode", "remote-gpt")]["tier"] == "B"  # the lie, killed
        # An allowlist name without the token is Tier B; with it, Tier A.
        assert by_cell[("codex", "qwen-local")]["tier"] == "A"
        assert by_cell[("codex", "remote-gpt")]["tier"] == "B"
        # Unknown harness, no verdict -> fail-closed Tier B.
        assert by_cell[("mystery-agent", "who-knows")]["tier"] == "B"
        # Labels stay structurally tier-distinct so a heatmap can never overlay them.
        assert by_cell[("opencode", "qwen-local")]["cell_label"].startswith("[A] ")
        assert by_cell[("opencode", "remote-gpt")]["cell_label"].startswith("[B] ")

    def test_excludes_non_battery_sessions(self, agentic_db: str) -> None:
        """Ad-hoc sessions with no scenario_id are not scoreboard cells."""
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            _insert_run(
                conn,
                session_id="adhoc",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id=None,  # not a battery run
                metrics={"task_success": 1.0},
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()

        records = [dict(zip(cols, row, strict=True)) for row in rows]
        assert records == []

    def test_empty_string_scenario_id_excluded(self, agentic_db: str) -> None:
        """A '' scenario_id is not a cell either (the WHERE ... <> '' clause).

        ``save_harness`` maps an empty scenario_id to SQL NULL, but the view
        guards ``<> ''`` too so a directly-written blank string can never form a
        phantom cell. Regression-pins that second half of the WHERE — the
        IS NOT NULL half alone would let '' through.
        """
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            _insert_run(
                conn,
                session_id="blank",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id="",  # empty string, not NULL
                metrics={"task_success": 1.0},
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()

        records = [dict(zip(cols, row, strict=True)) for row in rows]
        assert records == []

    def test_mixed_verdict_cell_never_promotes_untokened_rows(
        self, agentic_db: str
    ) -> None:
        """One cell mixing a token row and a legacy(NULL)/untokened row must never
        read Tier A over the untokened row -- the canonical post-migration state.

        Handed by test-design in the PR #374 FAIL verdict (red at that HEAD): the
        tier CASE read ``verified_local`` as a bare non-grouped column, so SQLite
        picked the tier from an ARBITRARY row of the group — with the token row
        first, the whole mixed cell (run_count=2, pass_rate over BOTH rows) was
        stamped Tier A. Green under the grain fix: the mixed population splits,
        and any Tier-A cell aggregates token rows only.
        """
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            # SAME (tool_name, model_id, scenario_id) -> one cell. Token row first.
            _insert_run(
                conn,
                session_id="mix_tok",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id="s_bugfix",
                verified_local=1,
                metrics={"task_success": 1.0},
            )
            _insert_run(
                conn,
                session_id="mix_legacy",
                tool_name="opencode",
                model_id="qwen-local",
                scenario_id="s_bugfix",
                verified_local=None,
                metrics={"task_success": 1.0},
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = [
                dict(zip(cols, r, strict=True))
                for r in conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()
            ]
        a_cells = [r for r in rows if r["tier"] == "A"]
        # No Tier-A cell may aggregate the untokened row. Under "split": an A cell
        # exists with run_count==1 (token only). Under "fail-closed": no A cell.
        # Under the pre-fix HEAD: one A cell with run_count==2 -> this fails.
        assert all(r["run_count"] == 1 for r in a_cells), (
            f"a Tier-A cell aggregated an untokened row: {a_cells!r}"
        )
        assert sum(r["run_count"] for r in a_cells) <= 1

    def test_mixed_cell_split_truth_table(self, agentic_db: str) -> None:
        """The chosen grain fix, pinned exactly: mixed cells SPLIT by verdict.

        Truth table over one (tool_name, model_id) at three scenarios:
          [1, NULL] -> A(run_count=1) + B(run_count=1)   the post-migration state
          [1, 0]    -> A(run_count=1) + B(run_count=1)   affirmative Tier-B kept out
          [1, 1]    -> A(run_count=2), no B cell         pure cells stay whole
        And population purity: each sub-cell's pass_rate is computed over ONLY its
        own rows — a Tier-A number is never contaminated by an untokened run, and
        an untokened run's result never vanishes (it lands in the B cell).
        """
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            # s_mix: token row PASSED, legacy NULL row FAILED -> purity visible.
            _insert_run(
                conn,
                session_id="t1",
                tool_name="opencode",
                model_id="m",
                scenario_id="s_mix",
                verified_local=1,
                metrics={"task_success": 1.0},
            )
            _insert_run(
                conn,
                session_id="l1",
                tool_name="opencode",
                model_id="m",
                scenario_id="s_mix",
                verified_local=None,
                metrics={"task_success": 0.0},
            )
            # s_10: token row + affirmative Tier-B row.
            _insert_run(
                conn,
                session_id="t2",
                tool_name="opencode",
                model_id="m",
                scenario_id="s_10",
                verified_local=1,
                metrics={"task_success": 1.0},
            )
            _insert_run(
                conn,
                session_id="b2",
                tool_name="opencode",
                model_id="m",
                scenario_id="s_10",
                verified_local=0,
                metrics={"task_success": 1.0},
            )
            # s_11: two token rows, one pass one fail -> one pure A cell.
            _insert_run(
                conn,
                session_id="t3",
                tool_name="opencode",
                model_id="m",
                scenario_id="s_11",
                verified_local=1,
                metrics={"task_success": 1.0},
            )
            _insert_run(
                conn,
                session_id="t4",
                tool_name="opencode",
                model_id="m",
                scenario_id="s_11",
                verified_local=1,
                metrics={"task_success": 0.0},
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = [
                dict(zip(cols, r, strict=True))
                for r in conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()
            ]

        cells = {(r["scenario_id"], r["tier"]): r for r in rows}
        assert len(rows) == len(cells)  # (scenario, tier) is the cell grain
        # [1, NULL] -> split; the A cell's pass_rate is over the token row ONLY.
        assert cells[("s_mix", "A")]["run_count"] == 1
        assert cells[("s_mix", "A")]["pass_rate"] == 1.0  # not dragged to 0.5
        assert cells[("s_mix", "B")]["run_count"] == 1
        assert cells[("s_mix", "B")]["pass_rate"] == 0.0  # legacy row not hidden
        # [1, 0] -> split identically.
        assert cells[("s_10", "A")]["run_count"] == 1
        assert cells[("s_10", "B")]["run_count"] == 1
        # [1, 1] -> one pure Tier-A cell, aggregated normally.
        assert cells[("s_11", "A")]["run_count"] == 2
        assert cells[("s_11", "A")]["pass_rate"] == 0.5
        assert ("s_11", "B") not in cells
        # Split sub-cells share the label prefix convention: tier baked in, so
        # they remain structurally distinct on every cell_label chart axis.
        assert cells[("s_mix", "A")]["cell_label"] == "[A] opencode @ m"
        assert cells[("s_mix", "B")]["cell_label"] == "[B] opencode @ m"

    def test_tier_derivation_pinned_to_persisted_verdict(self, agentic_db: str) -> None:
        """The view derives tier from the persisted ``verified_local`` verdict for
        EVERY name in the taxonomy — never from the tool_name (#350; #273 lesson).

        Pre-#350 the view read a bare ``tool_name IN ('opencode','codex')`` literal
        with no shared source of truth the comparison writer also read, so the two
        could diverge silently — an unpinned opencode/codex run was promoted to
        Tier A by its NAME. Now both sides ask the SAME question ("did this run
        resolve local?"), carried on one durable column: tier is a pure function of
        ``verified_local`` and INDEPENDENT of the name. This pins that
        name-independence across the whole canonical taxonomy
        (``rfc.harness_cli.TOOLS``) and the fail-closed NULL default — so a harness
        added to the taxonomy is automatically token-governed (fail-closed to Tier
        B until it mints the local-resolution token), never name-leaked either way.
        """
        import sqlite3

        from rfc.harness_cli import TOOLS
        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        # For EVERY taxonomy name, seed three runs at distinct cells: one that
        # minted the token (verified_local=1), one that did not (0), and one legacy
        # row with no verdict (NULL). The name is constant across all three; only
        # the persisted verdict differs, so any name-based promotion would show up.
        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            for i, tool in enumerate(TOOLS):
                _insert_run(
                    conn,
                    session_id=f"tax{i}-yes",
                    tool_name=tool,
                    model_id=f"local-{tool}",
                    scenario_id="s_yes",
                    verified_local=1,
                    metrics={"task_success": 1.0},
                )
                _insert_run(
                    conn,
                    session_id=f"tax{i}-no",
                    tool_name=tool,
                    model_id=f"remote-{tool}",
                    scenario_id="s_no",
                    verified_local=0,
                    metrics={"task_success": 1.0},
                )
                _insert_run(
                    conn,
                    session_id=f"tax{i}-legacy",
                    tool_name=tool,
                    model_id=f"legacy-{tool}",
                    scenario_id="s_legacy",
                    verified_local=None,
                    metrics={"task_success": 1.0},
                )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()

        by_cell = {
            (r["tool_name"], r["scenario_id"]): r
            for r in (dict(zip(cols, row, strict=True)) for row in rows)
        }
        for tool in TOOLS:
            # The token minted -> Tier A, whatever the name.
            assert by_cell[(tool, "s_yes")]["tier"] == "A", (
                f"{tool!r} with a minted token must be Tier A"
            )
            # No token -> Tier B, even for an allowlist name (the #350 fix).
            assert by_cell[(tool, "s_no")]["tier"] == "B", (
                f"{tool!r} without a token must be Tier B, not promoted by name"
            )
            # No verdict at all (legacy NULL) -> fail-closed Tier B.
            assert by_cell[(tool, "s_legacy")]["tier"] == "B", (
                f"{tool!r} with a NULL verdict must fail closed to Tier B"
            )
        # The ONLY Tier-A cells are the token-bearing ones — no name leaks in.
        tier_a_scenarios = {
            r["scenario_id"] for r in by_cell.values() if r["tier"] == "A"
        }
        assert tier_a_scenarios == {"s_yes"}

    def test_pass_rate_denominator_excludes_missing_task_success(
        self, agentic_db: str
    ) -> None:
        """NULL-skip semantics: run_count and pass_rate can have DIFFERENT Ns.

        ``pass_rate = AVG(task_success)`` skips runs with no task_success row,
        while ``run_count = COUNT(DISTINCT session_id)`` counts every run. So a
        run that produced no task_success verdict is EXCLUDED from the rate (not
        counted as a failure) yet still inflates run_count. Real battery runs
        always emit task_success (``compute_metrics``), so this never bites live
        data — but the divergence is pinned here so any future change to it is
        loud, and so a reader knows pass_rate's denominator is
        task_success-present runs, not run_count.
        """
        import sqlite3

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        db_path = agentic_db.removeprefix("sqlite:///")
        with sqlite3.connect(db_path) as conn:
            # Two adjudicated runs (1 pass, 1 fail) + one with NO task_success.
            _insert_run(
                conn,
                session_id="p1",
                tool_name="opencode",
                model_id="qwen",
                scenario_id="s_mix",
                metrics={"task_success": 1.0},
            )
            _insert_run(
                conn,
                session_id="p2",
                tool_name="opencode",
                model_id="qwen",
                scenario_id="s_mix",
                metrics={"task_success": 0.0},
            )
            _insert_run(
                conn,
                session_id="p3",
                tool_name="opencode",
                model_id="qwen",
                scenario_id="s_mix",
                metrics={"latency_ms": 500.0},  # no task_success verdict
            )
            # A cell with runs but ZERO task_success anywhere -> NULL pass, not 0.
            _insert_run(
                conn,
                session_id="q1",
                tool_name="opencode",
                model_id="qwen",
                scenario_id="s_none",
                metrics={"latency_ms": 100.0},
            )
            cols = _probe_columns(agentic_db, HARNESS_SCOREBOARD_VIEW_BODY)
            rows = conn.execute(HARNESS_SCOREBOARD_VIEW_BODY).fetchall()

        by_scenario = {
            r["scenario_id"]: r
            for r in (dict(zip(cols, row, strict=True)) for row in rows)
        }
        mix = by_scenario["s_mix"]
        assert mix["run_count"] == 3  # all three runs counted
        assert mix["pass_count"] == 1.0  # SUM over the two verdicts
        assert mix["pass_rate"] == 0.5  # AVG over {1.0, 0.0} — p3 EXCLUDED, not a fail
        none = by_scenario["s_none"]
        assert none["run_count"] == 1
        assert none["pass_count"] is None  # SUM of no rows is NULL, never 0
        assert none["pass_rate"] is None  # AVG of no rows is NULL, never 0


class TestScoreboardChartDefs:
    """Structural validity of the Harness Scoreboard dashboard-as-code."""

    def test_all_expected_charts_present(self) -> None:
        names = {c["slice_name"] for c in _SCOREBOARD_CHART_DEFS}
        assert SCOREBOARD_CHART_NAMES == names

    def test_no_duplicate_chart_names(self) -> None:
        names = [c["slice_name"] for c in _SCOREBOARD_CHART_DEFS]
        assert len(names) == len(set(names))

    def test_every_chart_has_required_fields(self) -> None:
        for c in _SCOREBOARD_CHART_DEFS:
            assert c.get("slice_name")
            assert c.get("viz_type")
            assert c.get("datasource_id_key")
            assert c.get("params")

    def test_charts_reference_registered_scoreboard_dataset(self) -> None:
        for c in _SCOREBOARD_CHART_DEFS:
            assert c["datasource_id_key"] == "harness_scoreboard"
        assert "harness_scoreboard" in _AGENTIC_DATASET_TABLES

    def test_chart_params_are_json_serializable(self) -> None:
        for c in _SCOREBOARD_CHART_DEFS:
            json.dumps(c["params"])

    def test_pass_rate_chart_is_heatmap(self) -> None:
        by_name = {c["slice_name"]: c for c in _SCOREBOARD_CHART_DEFS}
        assert by_name["Harness Pass Rate"]["viz_type"] == "heatmap_v2"

    def test_scoreboard_table_exposes_tier_column(self) -> None:
        by_name = {c["slice_name"]: c for c in _SCOREBOARD_CHART_DEFS}
        cols = by_name["Harness Scoreboard"]["params"]["columns"]
        assert "tier" in cols  # the column consumers must respect

    def test_comparative_charts_default_filter_tier_a(self) -> None:
        """Comparative charts default-filter tier='A'; the raw grid does not (#350/#347).

        A bar/heatmap that plots pass-rate or economy across harnesses is a
        head-to-head claim, honest only within the fixed-local Tier-A population,
        so each defaults to a tier == 'A' adhoc filter. The raw "Harness
        Scoreboard" TABLE is exempt — it exists to SHOW the tier separation across
        both tiers.
        """
        by_name = {c["slice_name"]: c for c in _SCOREBOARD_CHART_DEFS}

        def _tier_a_filters(params: dict) -> list:
            return [
                f
                for f in params.get("adhoc_filters", [])
                if f.get("subject") == "tier"
                and f.get("operator") == "=="
                and f.get("comparator") == "A"
            ]

        comparative = SCOREBOARD_CHART_NAMES - {"Harness Scoreboard"}
        for name in comparative:
            filters = _tier_a_filters(by_name[name]["params"])
            assert len(filters) == 1, (
                f"comparative chart {name!r} must default-filter tier='A' (#350)"
            )
            assert filters[0]["clause"] == "WHERE"

        # The honest raw grid must NOT be tier-filtered — it shows both tiers.
        assert _tier_a_filters(by_name["Harness Scoreboard"]["params"]) == []


class TestScoreboardLayoutAndFilters:
    """Layout wires every chart in; filters target the scoreboard dataset."""

    def test_layout_covers_all_charts(self) -> None:
        layout_names = {
            spec["name"]
            for section in _SCOREBOARD_LAYOUT_SECTIONS
            for spec in section["charts"]
        }
        assert SCOREBOARD_CHART_NAMES == layout_names

    def test_position_json_structure(self) -> None:
        chart_id_map = {
            name: i + 1 for i, name in enumerate(sorted(SCOREBOARD_CHART_NAMES))
        }
        layout = _build_scoreboard_position_json(chart_id_map)
        assert layout["ROOT_ID"]["type"] == "ROOT"
        assert layout["HEADER_ID"]["meta"]["text"] == "Harness Scoreboard"
        chart_keys = [k for k in layout if k.startswith("CHART-")]
        assert len(chart_keys) == len(SCOREBOARD_CHART_NAMES)

    def test_layout_is_json_serializable(self) -> None:
        chart_id_map = {
            name: i + 1 for i, name in enumerate(sorted(SCOREBOARD_CHART_NAMES))
        }
        json.dumps(_build_scoreboard_position_json(chart_id_map))

    def test_filter_names(self) -> None:
        names = {f["name"] for f in _SCOREBOARD_FILTER_CONFIGS}
        assert {"Tier", "Harness", "Scenario"} <= names

    def test_every_filter_targets_scoreboard(self) -> None:
        for f in _SCOREBOARD_FILTER_CONFIGS:
            assert f.get("id")
            assert f.get("targets")
            for target in f["targets"]:
                assert target["datasetId"] == "__SCOREBOARD_ID__"

    def test_filters_are_json_serializable(self) -> None:
        json.dumps(_SCOREBOARD_FILTER_CONFIGS)


class TestAgenticPhysicalDatasetRefresh:
    """#361: an existing PHYSICAL agentic dataset must be REFRESHED, not
    skipped. The bootstrap DDL is leaner than the canonical HarnessDatabase
    schema (by design), so a dataset first registered against a lean table has
    to re-fetch its metadata once HarnessDatabase's ADD COLUMN migrations land
    the spine columns -- otherwise the new coordinates stay invisible in
    dashboards until the dataset is recreated by hand.

    ``_create_agentic_datasets`` needs a live Superset app (``superset.db``),
    which the ops unit suite has no context for, so we inject a fake superset
    module and observe whether ``fetch_metadata()`` is (re)run on an existing
    dataset vs. a skip.
    """

    @staticmethod
    def _install_fake_superset(monkeypatch, existing_names):
        import types

        recorder: dict[str, list[str]] = {"refreshed": [], "created": []}

        class FakeSqlaTable:
            def __init__(
                self, table_name=None, database_id=None, schema=None, sql=None
            ):
                self.table_name = table_name
                self.database_id = database_id
                self.id = 999
                self.columns: list = []

            def fetch_metadata(self):
                recorder["created"].append(self.table_name)

        class FakeExisting:
            def __init__(self, table_name):
                self.table_name = table_name
                self.columns: list = []
                self.sql = None
                self.id = 1

            def fetch_metadata(self):
                recorder["refreshed"].append(self.table_name)

        existing_objs = {name: FakeExisting(name) for name in existing_names}

        class FakeQuery:
            def __init__(self):
                self._name = None

            def filter_by(self, table_name=None, database_id=None):
                self._name = table_name
                return self

            def first(self):
                return existing_objs.get(self._name)

        class FakeSession:
            def query(self, _model):
                return FakeQuery()

            def add(self, _obj):
                pass

            def commit(self):
                pass

        fake_superset = types.ModuleType("superset")
        fake_superset.db = types.SimpleNamespace(session=FakeSession())
        fake_connectors = types.ModuleType("superset.connectors")
        fake_sqla = types.ModuleType("superset.connectors.sqla")
        fake_models = types.ModuleType("superset.connectors.sqla.models")
        fake_models.SqlaTable = FakeSqlaTable
        monkeypatch.setitem(sys.modules, "superset", fake_superset)
        monkeypatch.setitem(sys.modules, "superset.connectors", fake_connectors)
        monkeypatch.setitem(sys.modules, "superset.connectors.sqla", fake_sqla)
        monkeypatch.setitem(sys.modules, "superset.connectors.sqla.models", fake_models)
        return recorder

    def _isolate_physical_loop(self, monkeypatch):
        import bootstrap_dashboards as bd

        # Only the physical loop under test; no virtual datasets, dummy uri.
        monkeypatch.setattr(bd, "_AGENTIC_VIRTUAL_DATASETS", {})
        monkeypatch.setattr(bd, "_AGENTIC_DATASET_TABLES", ["agentic_harnesses"])
        monkeypatch.setattr(bd, "_get_database_uri", lambda: "sqlite://")
        return bd

    def test_existing_physical_dataset_is_refreshed_not_skipped(self, monkeypatch):
        bd = self._isolate_physical_loop(monkeypatch)
        recorder = self._install_fake_superset(
            monkeypatch, existing_names=["agentic_harnesses"]
        )

        bd._create_agentic_datasets(db_id=7)

        # The pre-existing dataset re-fetched its metadata (picks up migrated
        # spine columns) instead of the old blunt `continue`.
        assert recorder["refreshed"] == ["agentic_harnesses"]
        assert recorder["created"] == []

    def test_absent_physical_dataset_is_still_created(self, monkeypatch):
        bd = self._isolate_physical_loop(monkeypatch)
        recorder = self._install_fake_superset(monkeypatch, existing_names=[])

        bd._create_agentic_datasets(db_id=7)

        assert recorder["created"] == ["agentic_harnesses"]
        assert recorder["refreshed"] == []


# ---------------------------------------------------------------------------
# Live-PostgreSQL validity guard (test-design's PR #374 handoff)
# ---------------------------------------------------------------------------
# Every scoreboard test above executes the view via sqlite3, and SQLite is
# PERMISSIVE about bare non-grouped columns — it silently picks an arbitrary
# row's value where PostgreSQL raises GroupingError. That backend blindness hid
# a view body that was invalid SQL on the production backend (PR #374 FAIL).
# This guard runs the real DDL against a live PostgreSQL in a scratch schema
# (dropped afterwards, never touching production tables), and skips-and-logs
# when no live PostgreSQL is reachable (the CLAUDE.md optional-dep posture).


def _live_postgres_engine():
    """Engine for the live RFC PostgreSQL, or None when unreachable.

    Resolution order: RFC_TEST_POSTGRES_URI env override, then POSTGRES_* env
    (compose conventions), then the compose host-port candidates on localhost.
    """
    import sqlalchemy as sa

    user = os.getenv("POSTGRES_USER", "rfc")
    password = os.getenv("POSTGRES_PASSWORD", "changeme")
    db = os.getenv("POSTGRES_DB", "rfc")
    candidates = []
    if os.getenv("RFC_TEST_POSTGRES_URI"):
        candidates.append(os.environ["RFC_TEST_POSTGRES_URI"])
    env_port = os.getenv("POSTGRES_PORT")
    ports = [env_port] if env_port else ["5434", "5433"]
    candidates += [f"postgresql://{user}:{password}@localhost:{p}/{db}" for p in ports]
    for uri in candidates:
        try:
            engine = sa.create_engine(uri, connect_args={"connect_timeout": 3})
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            return engine
        except Exception:  # unreachable candidate -- try the next
            continue
    return None


@pytest.fixture(scope="module")
def pg_engine():
    engine = _live_postgres_engine()
    if engine is None:
        pytest.skip("no live PostgreSQL reachable (start core/docker-compose.yml)")
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_scratch_schema(pg_engine):
    """A throwaway schema on the live PostgreSQL, dropped afterwards."""
    import uuid

    import sqlalchemy as sa

    schema = f"rfc_350_guard_{uuid.uuid4().hex[:12]}"
    with pg_engine.begin() as conn:
        conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
    try:
        yield schema
    finally:
        with pg_engine.begin() as conn:
            conn.execute(sa.text(f"DROP SCHEMA {schema} CASCADE"))


def _exec_agentic_ddl_pg(pg_engine, schema: str, ddl: str) -> None:
    """Execute the bootstrap DDL on PostgreSQL with _run_ddl's exact semantics
    (split on ';', strip comment lines, run the stripped statement, one
    transaction) -- scoped to the scratch schema via search_path."""
    import sqlalchemy as sa

    with pg_engine.begin() as conn:
        conn.execute(sa.text(f"SET search_path TO {schema}"))
        for statement in ddl.split(";"):
            executable = "\n".join(
                ln
                for ln in statement.splitlines()
                if ln.strip() and not ln.strip().startswith("--")
            ).strip()
            if executable:
                conn.execute(sa.text(executable))


class TestScoreboardPostgresValidity:
    """The scoreboard DDL and canonical view body are valid on PostgreSQL."""

    def test_bootstrap_ddl_runs_and_view_selects_on_postgres(
        self, pg_engine, pg_scratch_schema
    ) -> None:
        """The full _AGENTIC_TABLE_DDL executes on live PostgreSQL (twice --
        idempotent) and harness_scoreboard SELECTs cleanly. Red at the PR #374
        FAIL HEAD: CREATE VIEW raised GroupingError on the bare verified_local."""
        import sqlalchemy as sa

        for _ in range(2):
            _exec_agentic_ddl_pg(pg_engine, pg_scratch_schema, _AGENTIC_TABLE_DDL)
        with pg_engine.begin() as conn:
            conn.execute(sa.text(f"SET search_path TO {pg_scratch_schema}"))
            rows = conn.execute(sa.text("SELECT * FROM harness_scoreboard"))
            assert {"tier", "cell_label", "pass_rate"} <= set(rows.keys())

    def test_canonical_view_body_creates_and_selects_on_postgres(
        self, pg_engine, pg_scratch_schema
    ) -> None:
        """The canonical rfc.harness_db.HARNESS_SCOREBOARD_VIEW_BODY itself --
        not just the bootstrap copy -- is PostgreSQL-valid as CREATE VIEW and
        SELECT, over the canonical (migrated) table surface."""
        import sqlalchemy as sa

        from rfc.harness_db import HARNESS_SCOREBOARD_VIEW_BODY

        _exec_agentic_ddl_pg(pg_engine, pg_scratch_schema, _AGENTIC_TABLE_DDL)
        with pg_engine.begin() as conn:
            conn.execute(sa.text(f"SET search_path TO {pg_scratch_schema}"))
            conn.execute(
                sa.text(
                    "CREATE VIEW canonical_scoreboard AS\n"
                    + HARNESS_SCOREBOARD_VIEW_BODY
                )
            )
            conn.execute(sa.text("SELECT * FROM canonical_scoreboard")).fetchall()

    def test_upgrade_path_and_mixed_cell_split_on_postgres(
        self, pg_engine, pg_scratch_schema
    ) -> None:
        """The #660 upgrade path + the #374 mixed-cell semantics, on the REAL
        backend: an OLD-shape lean table (no scenario_id, no verified_local) is
        upgraded in place by the DDL's additive ALTERs, the view creates
        cleanly, and a mixed token/legacy cell SPLITS -- Tier A aggregates the
        token row only."""
        import sqlalchemy as sa

        with pg_engine.begin() as conn:
            conn.execute(sa.text(f"SET search_path TO {pg_scratch_schema}"))
            conn.execute(
                sa.text(
                    """
                    CREATE TABLE agentic_harnesses (
                        session_id              TEXT PRIMARY KEY,
                        tool_name               TEXT NOT NULL,
                        tool_version            TEXT,
                        model_id                TEXT,
                        rfc_version             TEXT,
                        branch                  TEXT,
                        started_at              TEXT NOT NULL,
                        ended_at                TEXT,
                        outcome                 TEXT,
                        replay_of_recording_id  TEXT
                    )
                    """
                )
            )
        _exec_agentic_ddl_pg(pg_engine, pg_scratch_schema, _AGENTIC_TABLE_DDL)
        with pg_engine.begin() as conn:
            conn.execute(sa.text(f"SET search_path TO {pg_scratch_schema}"))
            conn.execute(
                sa.text(
                    "INSERT INTO agentic_harnesses "
                    "(session_id, tool_name, model_id, scenario_id, "
                    " verified_local, started_at) VALUES "
                    "('tok', 'opencode', 'm', 's_mix', 1,    '2026-07-14T00:00:00'),"
                    "('leg', 'opencode', 'm', 's_mix', NULL, '2026-07-14T00:00:00')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO agentic_metrics "
                    "(id, session_id, metric_key, metric_value, recorded_at) VALUES "
                    "('m1', 'tok', 'task_success', 1.0, 't'),"
                    "('m2', 'leg', 'task_success', 1.0, 't')"
                )
            )
            cells = {
                (r.tier, r.run_count)
                for r in conn.execute(
                    sa.text("SELECT tier, run_count FROM harness_scoreboard")
                )
            }
        # Split semantics on the production backend: the mixed cell becomes a
        # pure Tier-A sub-cell (token row only) and a Tier-B sub-cell.
        assert cells == {("A", 1), ("B", 1)}
