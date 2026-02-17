"""Bootstrap Superset with Robot Framework test result dashboards.

Run inside the Superset container after `superset init` to create:
  - The actual PostgreSQL tables (test_runs, test_results, etc.)
  - A database connection to the RFC PostgreSQL tables
  - Datasets for test_runs, test_results, and models
  - Charts for pass rates, model comparison, trend lines, etc.
  - A "Robot Framework Results" dashboard
"""

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# SQL DDL for the Robot Framework result tables.
# Mirrors the schema from src/rfc/test_database.py so tables exist
# before Superset tries to fetch_metadata() on them.
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


def _ensure_tables(pg_uri: str) -> None:
    """Create the RFC result tables in PostgreSQL if they don't exist."""
    from sqlalchemy import create_engine, text  # type: ignore[import-untyped]

    engine = create_engine(pg_uri)
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL))
    engine.dispose()
    log.info("Ensured RFC result tables exist in PostgreSQL")


def _build_position_json(slices: list) -> str:
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
            "meta": {"text": "Robot Framework Test Results"},
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

        # ── 2. Datasets ────────────────────────────────────────────
        datasets = {}
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

        # ── 3. Charts (Slices) ─────────────────────────────────────
        chart_defs = [
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
                                "AVG(CAST(passed AS FLOAT) "
                                "/ NULLIF(total_tests, 0) * 100)"
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
                                "AVG(CAST(passed AS FLOAT) "
                                "/ NULLIF(total_tests, 0) * 100)"
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
        ]

        slices = []
        for cdef in chart_defs:
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
            slices.append(slc)

        # ── 4. Dashboard ───────────────────────────────────────────
        dash_title = "Robot Framework Test Results"
        dashboard = (
            db.session.query(Dashboard).filter_by(dashboard_title=dash_title).first()
        )
        if dashboard is None:
            dashboard = Dashboard(
                dashboard_title=dash_title,
                slug="rfc-results",
                position_json=_build_position_json(slices),
                published=True,
            )
            dashboard.slices = slices
            db.session.add(dashboard)
            log.info("Created dashboard: %s", dash_title)

        db.session.commit()
        log.info("Bootstrap complete")


if __name__ == "__main__":
    try:
        bootstrap()
    except Exception:
        log.exception("Bootstrap failed")
        sys.exit(1)
