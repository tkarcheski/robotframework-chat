"""Bootstrap Superset with Robot Framework test result dashboards.

Run inside the Superset container after ``superset init`` to create:
  - The 2 PostgreSQL tables (test_runs, test_results)
  - A database connection to the RFC PostgreSQL tables
  - Datasets for both tables
  - Charts covering test results and model performance
  - Two dashboards: Test Results, Model Performance

Redesigned schema: 2 tables only. output.xml is the source of truth.
"""

import logging
import os
import sys
from typing import Any

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL DDL — 2 tables only.
# ---------------------------------------------------------------------------
_TABLE_DDL = """
-- Drop old tables from pre-redesign schema
DROP TABLE IF EXISTS keyword_results CASCADE;
DROP TABLE IF EXISTS ollama_metrics CASCADE;
DROP TABLE IF EXISTS host_info CASCADE;
DROP TABLE IF EXISTS models CASCADE;
DROP TABLE IF EXISTS pipeline_results CASCADE;
DROP TABLE IF EXISTS robot_dry_run_results CASCADE;
DROP TABLE IF EXISTS analytics_model_trends CASCADE;
DROP TABLE IF EXISTS analytics_test_stability CASCADE;
DROP TABLE IF EXISTS analytics_model_comparison CASCADE;
DROP TABLE IF EXISTS analytics_regression_alerts CASCADE;
DROP TABLE IF EXISTS analytics_performance_fingerprints CASCADE;

CREATE TABLE IF NOT EXISTS test_runs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    test_suite VARCHAR(255) NOT NULL,
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    duration_seconds DOUBLE PRECISION,
    git_commit VARCHAR(255),
    git_branch VARCHAR(255),
    hostname VARCHAR(255),
    rfc_version VARCHAR(50),
    output_xml_url TEXT,
    output_xml_gz BYTEA,
    output_xml_source TEXT
);

CREATE TABLE IF NOT EXISTS test_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    test_name VARCHAR(500) NOT NULL,
    test_status VARCHAR(20) NOT NULL,
    score INTEGER,
    question TEXT,
    expected_answer TEXT,
    actual_answer TEXT,
    grading_reason TEXT,
    rfc_version VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_test_runs_model ON test_runs(model_name);
CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp);
CREATE INDEX IF NOT EXISTS idx_test_runs_suite ON test_runs(test_suite);
CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);
"""


def _get_database_uri() -> str:
    """Build the internal PostgreSQL URI for Superset (Docker-internal)."""
    pg_user = os.getenv("POSTGRES_USER", "rfc")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "changeme")
    pg_db = os.getenv("POSTGRES_DB", "rfc")
    pg_host = os.getenv("POSTGRES_HOST_INTERNAL", "postgres")
    pg_port = os.getenv("POSTGRES_PORT_INTERNAL", "5432")
    return f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"


def bootstrap() -> None:
    """Run the full bootstrap sequence."""
    try:
        from superset.app import create_app
    except ImportError:
        log.error("Superset is not installed. Run inside the Superset container.")
        sys.exit(1)

    app = create_app()

    with app.app_context():
        _create_tables()
        db_id = _ensure_database_connection()
        if db_id is None:
            log.error("Failed to create database connection.")
            sys.exit(1)
        _create_datasets(db_id)
        _create_charts_and_dashboards(db_id)

    log.info("Bootstrap complete.")


def _create_tables() -> None:
    """Create the 2-table schema in PostgreSQL."""
    from sqlalchemy import create_engine, text

    uri = _get_database_uri()
    engine = create_engine(uri)
    with engine.begin() as conn:
        for statement in _TABLE_DDL.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
    engine.dispose()
    log.info("Created 2-table schema (test_runs, test_results).")


def _ensure_database_connection() -> int | None:
    """Create or update the Superset database connection object."""
    from superset import db as superset_db
    from superset.models.core import Database

    db_name = "Robot Framework Results"
    uri = _get_database_uri()

    existing = (
        superset_db.session.query(Database)
        .filter_by(database_name=db_name)
        .first()
    )
    if existing:
        existing.sqlalchemy_uri = uri
        superset_db.session.commit()
        log.info(f"Updated database connection: {db_name} (id={existing.id})")
        return existing.id

    new_db = Database(
        database_name=db_name,
        sqlalchemy_uri=uri,
        expose_in_sqllab=True,
    )
    superset_db.session.add(new_db)
    superset_db.session.commit()
    log.info(f"Created database connection: {db_name} (id={new_db.id})")
    return new_db.id


def _create_datasets(db_id: int) -> None:
    """Create Superset datasets for the 2 tables."""
    from superset import db as superset_db
    from superset.connectors.sqla.models import SqlaTable

    tables = ["test_runs", "test_results"]
    for table_name in tables:
        existing = (
            superset_db.session.query(SqlaTable)
            .filter_by(table_name=table_name, database_id=db_id)
            .first()
        )
        if existing:
            log.info(f"Dataset already exists: {table_name}")
            continue

        dataset = SqlaTable(
            table_name=table_name,
            database_id=db_id,
            schema=None,
        )
        superset_db.session.add(dataset)
        superset_db.session.commit()

        # Fetch metadata to populate columns
        try:
            dataset.fetch_metadata()
            superset_db.session.commit()
        except Exception as e:
            log.warning(f"fetch_metadata failed for {table_name}: {e}")

        log.info(f"Created dataset: {table_name} (id={dataset.id})")


def _create_charts_and_dashboards(db_id: int) -> None:
    """Create charts and 2 dashboards for the 2-table schema."""
    from superset import db as superset_db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    # Get dataset IDs
    datasets: dict[str, int] = {}
    for table_name in ["test_runs", "test_results"]:
        ds = (
            superset_db.session.query(SqlaTable)
            .filter_by(table_name=table_name, database_id=db_id)
            .first()
        )
        if ds:
            datasets[table_name] = ds.id

    if not datasets:
        log.warning("No datasets found; skipping chart creation.")
        return

    # Chart definitions
    charts: list[dict[str, Any]] = []

    if "test_runs" in datasets:
        ds_id = datasets["test_runs"]
        charts.extend([
            {
                "slice_name": "Pass Rate Over Time by Model",
                "viz_type": "echarts_timeseries_line",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["passed"],
                    "groupby": ["model_name"],
                    "time_column": "timestamp",
                },
            },
            {
                "slice_name": "Model Comparison — Pass Rate",
                "viz_type": "echarts_bar",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["passed", "failed"],
                    "groupby": ["model_name"],
                },
            },
            {
                "slice_name": "Suite Duration Trend",
                "viz_type": "echarts_timeseries_line",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["duration_seconds"],
                    "groupby": ["model_name"],
                    "time_column": "timestamp",
                },
            },
            {
                "slice_name": "Recent Test Runs",
                "viz_type": "table",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "columns": [
                        "timestamp", "model_name", "hostname",
                        "test_suite", "passed", "failed",
                        "duration_seconds", "output_xml_source",
                        "output_xml_url",
                    ],
                    "order_desc": True,
                    "row_limit": 100,
                },
            },
            {
                "slice_name": "Avg Duration by Model",
                "viz_type": "echarts_bar",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["duration_seconds"],
                    "groupby": ["model_name"],
                },
            },
            {
                "slice_name": "Tests Per Model",
                "viz_type": "echarts_bar",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["total_tests"],
                    "groupby": ["model_name"],
                },
            },
            {
                "slice_name": "Pass Rate by Hostname",
                "viz_type": "echarts_bar",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["passed", "failed"],
                    "groupby": ["hostname"],
                },
            },
            {
                "slice_name": "Model Performance by Host",
                "viz_type": "echarts_timeseries_line",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["passed"],
                    "groupby": ["model_name", "hostname"],
                    "time_column": "timestamp",
                },
            },
            {
                "slice_name": "Tests Per Host",
                "viz_type": "echarts_bar",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["total_tests"],
                    "groupby": ["hostname"],
                },
            },
        ])

    if "test_results" in datasets:
        ds_id = datasets["test_results"]
        charts.extend([
            {
                "slice_name": "Test Status Breakdown",
                "viz_type": "pie",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["count"],
                    "groupby": ["test_status"],
                },
            },
            {
                "slice_name": "Failures by Test Name",
                "viz_type": "echarts_bar",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["count"],
                    "groupby": ["test_name"],
                    "adhoc_filters": [
                        {"clause": "WHERE", "expressionType": "SIMPLE",
                         "subject": "test_status", "operator": "==",
                         "comparator": "FAIL"},
                    ],
                },
            },
            {
                "slice_name": "Score Distribution",
                "viz_type": "echarts_bar",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "metrics": ["count"],
                    "groupby": ["score"],
                },
            },
            {
                "slice_name": "Test Results Detail",
                "viz_type": "table",
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": {
                    "columns": [
                        "test_name", "test_status", "score",
                        "question", "actual_answer", "grading_reason",
                    ],
                    "order_desc": True,
                    "row_limit": 200,
                },
            },
        ])

    # Create charts
    import json

    chart_ids: list[int] = []
    for chart_def in charts:
        existing = (
            superset_db.session.query(Slice)
            .filter_by(slice_name=chart_def["slice_name"])
            .first()
        )
        if existing:
            chart_ids.append(existing.id)
            log.info(f"Chart already exists: {chart_def['slice_name']}")
            continue

        chart = Slice(
            slice_name=chart_def["slice_name"],
            viz_type=chart_def["viz_type"],
            datasource_id=chart_def["datasource_id"],
            datasource_type=chart_def["datasource_type"],
            params=json.dumps(chart_def["params"]),
        )
        superset_db.session.add(chart)
        superset_db.session.commit()
        chart_ids.append(chart.id)
        log.info(f"Created chart: {chart_def['slice_name']} (id={chart.id})")

    # Create dashboards
    _dashboards = [
        {
            "dashboard_title": "Test Results",
            "slug": "test-results",
        },
        {
            "dashboard_title": "Model Performance",
            "slug": "model-performance",
        },
    ]
    for dash_def in _dashboards:
        existing = (
            superset_db.session.query(Dashboard)
            .filter_by(slug=dash_def["slug"])
            .first()
        )
        if existing:
            log.info(f"Dashboard already exists: {dash_def['dashboard_title']}")
            continue

        dashboard = Dashboard(
            dashboard_title=dash_def["dashboard_title"],
            slug=dash_def["slug"],
            published=True,
        )
        # Associate all charts with both dashboards
        dashboard.slices = [
            superset_db.session.query(Slice).get(cid)
            for cid in chart_ids
            if superset_db.session.query(Slice).get(cid)
        ]
        superset_db.session.add(dashboard)
        superset_db.session.commit()
        log.info(
            f"Created dashboard: {dash_def['dashboard_title']} (id={dashboard.id})"
        )


if __name__ == "__main__":
    bootstrap()
