"""Bootstrap Superset with Robot Framework test result dashboards.

Run inside the Superset container after ``superset init`` to create:
  - The actual PostgreSQL tables (test_runs, test_results, etc.)
  - SQL views for cross-table analysis
  - A database connection to the RFC PostgreSQL tables
  - Datasets for all tables and virtual datasets for JOINed views
  - Charts covering test results, pipelines, models, dry runs
  - Three dashboards: Test Results, Pipeline Health, Model Analytics
"""

import json
import logging
import os
import sys
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL DDL for the Robot Framework result tables.
# Mirrors the schema from src/rfc/test_database.py so tables exist
# before Superset tries to fetch_metadata() on them.
# ---------------------------------------------------------------------------
_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS test_runs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    model_release_date VARCHAR(255),
    model_parameters VARCHAR(255),
    test_suite VARCHAR(255) NOT NULL,
    git_commit VARCHAR(255),
    git_branch VARCHAR(255),
    pipeline_url TEXT,
    runner_id VARCHAR(255),
    runner_tags TEXT,
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    duration_seconds DOUBLE PRECISION,
    rfc_version VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS test_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    test_name VARCHAR(255) NOT NULL,
    test_status VARCHAR(50) NOT NULL,
    score INTEGER,
    question TEXT,
    expected_answer TEXT,
    actual_answer TEXT,
    grading_reason TEXT
);

CREATE TABLE IF NOT EXISTS models (
    name VARCHAR(255) PRIMARY KEY,
    full_name VARCHAR(255),
    organization VARCHAR(255),
    release_date VARCHAR(255),
    parameters VARCHAR(255),
    last_tested TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_results (
    id SERIAL PRIMARY KEY,
    pipeline_id BIGINT NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL,
    ref VARCHAR(255) NOT NULL,
    sha VARCHAR(255) NOT NULL,
    web_url TEXT NOT NULL,
    created_at VARCHAR(255),
    updated_at VARCHAR(255),
    source VARCHAR(255),
    duration_seconds DOUBLE PRECISION,
    queued_duration_seconds DOUBLE PRECISION,
    tag INTEGER,
    jobs_fetched INTEGER DEFAULT 0,
    artifacts_found INTEGER DEFAULT 0,
    synced_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS robot_dry_run_results (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    test_suite VARCHAR(255) NOT NULL,
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    duration_seconds DOUBLE PRECISION,
    git_commit VARCHAR(255),
    git_branch VARCHAR(255),
    rfc_version VARCHAR(50),
    errors TEXT
);

CREATE INDEX IF NOT EXISTS idx_test_runs_model ON test_runs(model_name);
CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp);
CREATE INDEX IF NOT EXISTS idx_test_runs_suite ON test_runs(test_suite);
CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_results_pipeline_id
    ON pipeline_results(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_results_ref ON pipeline_results(ref);
CREATE INDEX IF NOT EXISTS idx_pipeline_results_status
    ON pipeline_results(status);
CREATE INDEX IF NOT EXISTS idx_dry_run_results_timestamp
    ON robot_dry_run_results(timestamp);
CREATE INDEX IF NOT EXISTS idx_dry_run_results_suite
    ON robot_dry_run_results(test_suite);
"""

# ---------------------------------------------------------------------------
# SQL for virtual datasets (JOINed views for cross-table analysis).
# These are registered as Superset virtual datasets, not DB views,
# so they work without DDL privileges.
# ---------------------------------------------------------------------------
_VIRTUAL_DATASETS: Dict[str, str] = {
    "test_results_detail": """
        SELECT
            tr.id AS result_id,
            tr.test_name,
            tr.test_status,
            tr.score,
            tr.question,
            tr.expected_answer,
            tr.actual_answer,
            tr.grading_reason,
            runs.timestamp,
            runs.model_name,
            runs.test_suite,
            runs.git_branch,
            runs.git_commit,
            runs.duration_seconds AS run_duration
        FROM test_results tr
        JOIN test_runs runs ON tr.run_id = runs.id
    """,
    "model_suite_performance": """
        SELECT
            model_name,
            test_suite,
            COUNT(*) AS run_count,
            AVG(CAST(passed AS FLOAT) / NULLIF(total_tests, 0) * 100)
                AS avg_pass_rate,
            AVG(duration_seconds) AS avg_duration,
            SUM(passed) AS total_passed,
            SUM(failed) AS total_failed,
            MAX(timestamp) AS last_run
        FROM test_runs
        WHERE total_tests > 0
        GROUP BY model_name, test_suite
    """,
}


# ---------------------------------------------------------------------------
# Chart definitions — grouped by dashboard
# ---------------------------------------------------------------------------


def _test_results_charts(datasets: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Charts for the Test Results dashboard."""
    return [
        {
            "name": "Pass Rate Over Time",
            "viz_type": "line",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "line",
                "granularity_sqla": "timestamp",
                "time_grain_sqla": "P1D",
                "metrics": [
                    {
                        "label": "pass_rate",
                        "expressionType": "SQL",
                        "sqlExpression": (
                            "AVG(CAST(passed AS FLOAT) / NULLIF(total_tests, 0) * 100)"
                        ),
                    }
                ],
                "groupby": ["model_name"],
                "row_limit": 10000,
                "color_scheme": "supersetColors",
                "show_legend": True,
                "y_axis_label": "Pass Rate (%)",
            },
        },
        {
            "name": "Model Comparison - Pass Rate",
            "viz_type": "bar",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "avg_pass_rate",
                        "expressionType": "SQL",
                        "sqlExpression": (
                            "AVG(CAST(passed AS FLOAT) / NULLIF(total_tests, 0) * 100)"
                        ),
                    }
                ],
                "groupby": ["model_name"],
                "row_limit": 50,
                "color_scheme": "supersetColors",
                "show_legend": False,
                "y_axis_label": "Avg Pass Rate (%)",
            },
        },
        {
            "name": "Test Results Breakdown",
            "viz_type": "pie",
            "datasource": datasets["test_results"],
            "params": {
                "viz_type": "pie",
                "metrics": [
                    {
                        "label": "count",
                        "expressionType": "SIMPLE",
                        "aggregate": "COUNT",
                        "column": {"column_name": "id"},
                    }
                ],
                "groupby": ["test_status"],
                "color_scheme": "supersetColors",
                "show_legend": True,
                "show_labels": True,
            },
        },
        {
            "name": "Test Suite Duration Trend",
            "viz_type": "line",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "line",
                "granularity_sqla": "timestamp",
                "time_grain_sqla": "P1D",
                "metrics": [
                    {
                        "label": "avg_duration",
                        "expressionType": "SQL",
                        "sqlExpression": "AVG(duration_seconds)",
                    }
                ],
                "groupby": ["test_suite"],
                "row_limit": 10000,
                "color_scheme": "supersetColors",
                "show_legend": True,
                "y_axis_label": "Duration (s)",
            },
        },
        {
            "name": "Recent Test Runs",
            "viz_type": "table",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "table",
                "all_columns": [
                    "timestamp",
                    "model_name",
                    "test_suite",
                    "passed",
                    "failed",
                    "skipped",
                    "duration_seconds",
                    "git_branch",
                ],
                "order_desc": True,
                "row_limit": 50,
                "order_by_cols": '["timestamp"]',
            },
        },
        {
            "name": "Failures by Test Name",
            "viz_type": "bar",
            "datasource": datasets["test_results"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "failures",
                        "expressionType": "SIMPLE",
                        "aggregate": "COUNT",
                        "column": {"column_name": "id"},
                    }
                ],
                "adhoc_filters": [
                    {
                        "clause": "WHERE",
                        "expressionType": "SIMPLE",
                        "subject": "test_status",
                        "operator": "==",
                        "comparator": "FAIL",
                    }
                ],
                "groupby": ["test_name"],
                "row_limit": 20,
                "color_scheme": "supersetColors",
                "y_axis_label": "Failure Count",
            },
        },
        # ── New charts ────────────────────────────────────────────────
        {
            "name": "Pass Rate by Branch",
            "viz_type": "bar",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "avg_pass_rate",
                        "expressionType": "SQL",
                        "sqlExpression": (
                            "AVG(CAST(passed AS FLOAT) / NULLIF(total_tests, 0) * 100)"
                        ),
                    }
                ],
                "groupby": ["git_branch"],
                "row_limit": 30,
                "color_scheme": "supersetColors",
                "y_axis_label": "Avg Pass Rate (%)",
            },
        },
        {
            "name": "Pass Rate by Suite",
            "viz_type": "bar",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "avg_pass_rate",
                        "expressionType": "SQL",
                        "sqlExpression": (
                            "AVG(CAST(passed AS FLOAT) / NULLIF(total_tests, 0) * 100)"
                        ),
                    }
                ],
                "groupby": ["test_suite"],
                "row_limit": 30,
                "color_scheme": "supersetColors",
                "y_axis_label": "Avg Pass Rate (%)",
            },
        },
        {
            "name": "Score Distribution",
            "viz_type": "bar",
            "datasource": datasets["test_results_detail"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "count",
                        "expressionType": "SQL",
                        "sqlExpression": "COUNT(*)",
                    }
                ],
                "adhoc_filters": [
                    {
                        "clause": "WHERE",
                        "expressionType": "SQL",
                        "sqlExpression": "score IS NOT NULL",
                    }
                ],
                "groupby": ["model_name", "score"],
                "row_limit": 100,
                "color_scheme": "supersetColors",
                "y_axis_label": "Test Count",
            },
        },
        {
            "name": "Test Results Detail",
            "viz_type": "table",
            "datasource": datasets["test_results_detail"],
            "params": {
                "viz_type": "table",
                "all_columns": [
                    "timestamp",
                    "model_name",
                    "test_suite",
                    "test_name",
                    "test_status",
                    "score",
                    "actual_answer",
                    "grading_reason",
                ],
                "order_desc": True,
                "row_limit": 100,
                "order_by_cols": '["timestamp"]',
            },
        },
    ]


def _pipeline_health_charts(datasets: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Charts for the Pipeline Health dashboard."""
    return [
        {
            "name": "Pipeline Status Distribution",
            "viz_type": "pie",
            "datasource": datasets["pipeline_results"],
            "params": {
                "viz_type": "pie",
                "metrics": [
                    {
                        "label": "count",
                        "expressionType": "SIMPLE",
                        "aggregate": "COUNT",
                        "column": {"column_name": "id"},
                    }
                ],
                "groupby": ["status"],
                "color_scheme": "supersetColors",
                "show_legend": True,
                "show_labels": True,
            },
        },
        {
            "name": "Pipeline Duration Over Time",
            "viz_type": "line",
            "datasource": datasets["pipeline_results"],
            "params": {
                "viz_type": "line",
                "granularity_sqla": "synced_at",
                "time_grain_sqla": "P1D",
                "metrics": [
                    {
                        "label": "avg_duration",
                        "expressionType": "SQL",
                        "sqlExpression": "AVG(duration_seconds)",
                    }
                ],
                "row_limit": 10000,
                "color_scheme": "supersetColors",
                "show_legend": True,
                "y_axis_label": "Duration (s)",
            },
        },
        {
            "name": "Pipeline Queue Time",
            "viz_type": "line",
            "datasource": datasets["pipeline_results"],
            "params": {
                "viz_type": "line",
                "granularity_sqla": "synced_at",
                "time_grain_sqla": "P1D",
                "metrics": [
                    {
                        "label": "avg_queue_time",
                        "expressionType": "SQL",
                        "sqlExpression": "AVG(queued_duration_seconds)",
                    }
                ],
                "row_limit": 10000,
                "color_scheme": "supersetColors",
                "y_axis_label": "Queue Time (s)",
            },
        },
        {
            "name": "Pipelines by Branch",
            "viz_type": "bar",
            "datasource": datasets["pipeline_results"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "count",
                        "expressionType": "SIMPLE",
                        "aggregate": "COUNT",
                        "column": {"column_name": "id"},
                    }
                ],
                "groupby": ["ref"],
                "row_limit": 20,
                "color_scheme": "supersetColors",
                "y_axis_label": "Pipeline Count",
            },
        },
        {
            "name": "Pipeline Success Rate Over Time",
            "viz_type": "line",
            "datasource": datasets["pipeline_results"],
            "params": {
                "viz_type": "line",
                "granularity_sqla": "synced_at",
                "time_grain_sqla": "P1W",
                "metrics": [
                    {
                        "label": "success_rate",
                        "expressionType": "SQL",
                        "sqlExpression": (
                            "AVG(CASE WHEN status = 'success'"
                            " THEN 1.0 ELSE 0.0 END) * 100"
                        ),
                    }
                ],
                "row_limit": 10000,
                "color_scheme": "supersetColors",
                "y_axis_label": "Success Rate (%)",
            },
        },
        {
            "name": "Recent Pipelines",
            "viz_type": "table",
            "datasource": datasets["pipeline_results"],
            "params": {
                "viz_type": "table",
                "all_columns": [
                    "pipeline_id",
                    "status",
                    "ref",
                    "sha",
                    "source",
                    "duration_seconds",
                    "queued_duration_seconds",
                    "jobs_fetched",
                    "artifacts_found",
                    "synced_at",
                ],
                "order_desc": True,
                "row_limit": 50,
                "order_by_cols": '["pipeline_id"]',
            },
        },
    ]


def _model_analytics_charts(datasets: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Charts for the Model Analytics dashboard."""
    return [
        {
            "name": "Model Catalog",
            "viz_type": "table",
            "datasource": datasets["models"],
            "params": {
                "viz_type": "table",
                "all_columns": [
                    "name",
                    "full_name",
                    "organization",
                    "release_date",
                    "parameters",
                    "last_tested",
                ],
                "order_desc": True,
                "row_limit": 100,
                "order_by_cols": '["last_tested"]',
            },
        },
        {
            "name": "Model x Suite Performance",
            "viz_type": "table",
            "datasource": datasets["model_suite_performance"],
            "params": {
                "viz_type": "table",
                "all_columns": [
                    "model_name",
                    "test_suite",
                    "run_count",
                    "avg_pass_rate",
                    "avg_duration",
                    "total_passed",
                    "total_failed",
                    "last_run",
                ],
                "order_desc": True,
                "row_limit": 200,
                "order_by_cols": '["last_run"]',
            },
        },
        {
            "name": "Tests Per Model",
            "viz_type": "bar",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "total_runs",
                        "expressionType": "SIMPLE",
                        "aggregate": "COUNT",
                        "column": {"column_name": "id"},
                    }
                ],
                "groupby": ["model_name"],
                "row_limit": 50,
                "color_scheme": "supersetColors",
                "y_axis_label": "Number of Runs",
            },
        },
        {
            "name": "Avg Duration by Model",
            "viz_type": "bar",
            "datasource": datasets["test_runs"],
            "params": {
                "viz_type": "bar",
                "metrics": [
                    {
                        "label": "avg_duration",
                        "expressionType": "SQL",
                        "sqlExpression": "AVG(duration_seconds)",
                    }
                ],
                "groupby": ["model_name"],
                "row_limit": 50,
                "color_scheme": "supersetColors",
                "y_axis_label": "Avg Duration (s)",
            },
        },
        {
            "name": "Dry Run Validation Trend",
            "viz_type": "line",
            "datasource": datasets["robot_dry_run_results"],
            "params": {
                "viz_type": "line",
                "granularity_sqla": "timestamp",
                "time_grain_sqla": "P1D",
                "metrics": [
                    {
                        "label": "pass_rate",
                        "expressionType": "SQL",
                        "sqlExpression": (
                            "AVG(CAST(passed AS FLOAT) / NULLIF(total_tests, 0) * 100)"
                        ),
                    }
                ],
                "groupby": ["test_suite"],
                "row_limit": 10000,
                "color_scheme": "supersetColors",
                "y_axis_label": "Pass Rate (%)",
            },
        },
        {
            "name": "Recent Dry Runs",
            "viz_type": "table",
            "datasource": datasets["robot_dry_run_results"],
            "params": {
                "viz_type": "table",
                "all_columns": [
                    "timestamp",
                    "test_suite",
                    "total_tests",
                    "passed",
                    "failed",
                    "skipped",
                    "duration_seconds",
                    "git_branch",
                    "errors",
                ],
                "order_desc": True,
                "row_limit": 50,
                "order_by_cols": '["timestamp"]',
            },
        },
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_tables(pg_uri: str) -> None:
    """Create the RFC result tables in PostgreSQL if they don't exist."""
    from sqlalchemy import create_engine, text  # type: ignore[import-untyped]

    engine = create_engine(pg_uri)
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL))
    engine.dispose()
    log.info("Ensured RFC result tables exist in PostgreSQL")


def _build_position_json(slices: list, title: str) -> str:
    """Build a valid Superset dashboard position_json.

    Superset requires ROOT_ID, GRID_ID, HEADER_ID, and ROW wrappers
    around CHART components.  Charts are arranged in rows of 2.
    """
    position: dict = {
        "ROOT_ID": {
            "type": "ROOT",
            "id": "ROOT_ID",
            "children": ["GRID_ID"],
        },
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
        },
        "HEADER_ID": {
            "type": "HEADER",
            "id": "HEADER_ID",
            "meta": {"text": title},
        },
    }

    # Arrange charts in rows of 2
    row_idx = 0
    for i in range(0, len(slices), 2):
        row_id = f"ROW-{row_idx}"
        row_children = []

        for slc in slices[i : i + 2]:
            chart_id = f"CHART-{slc.id}"
            position[chart_id] = {
                "type": "CHART",
                "id": chart_id,
                "children": [],
                "meta": {
                    "width": 6,
                    "height": 50,
                    "chartId": slc.id,
                    "sliceName": slc.slice_name,
                },
            }
            row_children.append(chart_id)

        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": row_children,
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        position["GRID_ID"]["children"].append(row_id)
        row_idx += 1

    return json.dumps(position)


def _get_or_create_slice(db: Any, Slice: Any, cdef: Dict[str, Any]) -> Any:
    """Get an existing chart or create a new one."""
    slc = db.session.query(Slice).filter_by(slice_name=cdef["name"]).first()
    if slc is None:
        ds = cdef["datasource"]
        slc = Slice(
            slice_name=cdef["name"],
            viz_type=cdef["viz_type"],
            datasource_id=ds.id,
            datasource_type="table",
            params=json.dumps(cdef["params"]),
        )
        db.session.add(slc)
        db.session.flush()
        log.info("Created chart: %s", cdef["name"])
    return slc


def _get_or_create_dashboard(
    db: Any, Dashboard: Any, title: str, slug: str, slices: list
) -> Any:
    """Get an existing dashboard or create a new one with charts."""
    dashboard = db.session.query(Dashboard).filter_by(dashboard_title=title).first()
    if dashboard is None:
        dashboard = Dashboard(
            dashboard_title=title,
            slug=slug,
            position_json=_build_position_json(slices, title),
            published=True,
        )
        dashboard.slices = slices
        db.session.add(dashboard)
        log.info("Created dashboard: %s", title)
    return dashboard


# ---------------------------------------------------------------------------
# Main bootstrap
# ---------------------------------------------------------------------------


def bootstrap() -> None:
    # Import Superset internals (available inside the container)
    from superset.app import create_app  # type: ignore[import-untyped]

    app = create_app()

    with app.app_context():
        from superset import db  # type: ignore[import-untyped,attr-defined]
        from superset.connectors.sqla.models import (  # type: ignore[import-untyped]
            SqlaTable,
        )
        from superset.models.core import Database  # type: ignore[import-untyped]
        from superset.models.dashboard import (  # type: ignore[import-untyped]
            Dashboard,
        )
        from superset.models.slice import Slice  # type: ignore[import-untyped]

        # Build connection URI from env (same vars docker-compose sets)
        pg_user = os.getenv("POSTGRES_USER", "rfc")
        pg_pass = os.getenv("POSTGRES_PASSWORD", "rfc")
        pg_db = os.getenv("POSTGRES_DB", "rfc")
        pg_uri = f"postgresql://{pg_user}:{pg_pass}@postgres:5432/{pg_db}"

        # ── 0. Create RFC tables in PostgreSQL ────────────────────────
        _ensure_tables(pg_uri)

        # ── 1. Database connection ──────────────────────────────────
        db_name = "Robot Framework Results"
        database = db.session.query(Database).filter_by(database_name=db_name).first()
        if database is None:
            database = Database(
                database_name=db_name,
                sqlalchemy_uri=pg_uri,
                expose_in_sqllab=True,
            )
            db.session.add(database)
            db.session.flush()
            log.info("Created database connection: %s", db_name)
        else:
            log.info("Database connection already exists: %s", db_name)

        # ── 2. Physical table datasets ────────────────────────────────
        datasets: Dict[str, Any] = {}
        for table_name in (
            "test_runs",
            "test_results",
            "models",
            "pipeline_results",
            "robot_dry_run_results",
        ):
            ds = (
                db.session.query(SqlaTable)
                .filter_by(table_name=table_name, database_id=database.id)
                .first()
            )
            if ds is None:
                ds = SqlaTable(
                    table_name=table_name,
                    database_id=database.id,
                    schema=None,
                )
                db.session.add(ds)
                db.session.flush()
                log.info("Created dataset: %s", table_name)
            # Sync column metadata so Superset knows the schema
            try:
                ds.fetch_metadata()
                db.session.flush()
                log.info("Synced columns for: %s", table_name)
            except Exception as e:
                log.warning("Could not sync columns for %s: %s", table_name, e)
            datasets[table_name] = ds

        # ── 3. Virtual datasets (SQL queries for cross-table views) ──
        for vds_name, sql in _VIRTUAL_DATASETS.items():
            ds = (
                db.session.query(SqlaTable)
                .filter_by(table_name=vds_name, database_id=database.id)
                .first()
            )
            if ds is None:
                ds = SqlaTable(
                    table_name=vds_name,
                    database_id=database.id,
                    schema=None,
                    sql=sql,
                )
                db.session.add(ds)
                db.session.flush()
                log.info("Created virtual dataset: %s", vds_name)
            try:
                ds.fetch_metadata()
                db.session.flush()
                log.info("Synced columns for virtual dataset: %s", vds_name)
            except Exception as e:
                log.warning("Could not sync columns for %s: %s", vds_name, e)
            datasets[vds_name] = ds

        # ── 4. Charts ────────────────────────────────────────────────
        test_result_slices = [
            _get_or_create_slice(db, Slice, cdef)
            for cdef in _test_results_charts(datasets)
        ]
        pipeline_slices = [
            _get_or_create_slice(db, Slice, cdef)
            for cdef in _pipeline_health_charts(datasets)
        ]
        model_slices = [
            _get_or_create_slice(db, Slice, cdef)
            for cdef in _model_analytics_charts(datasets)
        ]

        # ── 5. Dashboards ───────────────────────────────────────────
        _get_or_create_dashboard(
            db,
            Dashboard,
            "Robot Framework Test Results",
            "rfc-results",
            test_result_slices,
        )
        _get_or_create_dashboard(
            db,
            Dashboard,
            "Pipeline Health",
            "rfc-pipelines",
            pipeline_slices,
        )
        _get_or_create_dashboard(
            db,
            Dashboard,
            "Model Analytics",
            "rfc-models",
            model_slices,
        )

        db.session.commit()
        log.info("Bootstrap complete — 3 dashboards created")


if __name__ == "__main__":
    try:
        bootstrap()
    except Exception:
        log.exception("Bootstrap failed")
        sys.exit(1)
