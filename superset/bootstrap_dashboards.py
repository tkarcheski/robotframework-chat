"""Bootstrap Superset with Robot Framework test result dashboards.

Run inside the Superset container after `superset init` to create:
  - A database connection to the RFC PostgreSQL tables
  - Datasets for test_runs, test_results, and models
  - Charts for pass rates, model comparison, trend lines, etc.
  - A "Robot Framework Results" dashboard
"""

import logging
import sys

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def bootstrap() -> None:
    # Import Superset internals (available inside the container)
    from superset.app import create_app  # type: ignore[import-untyped]

    app = create_app()

    with app.app_context():
        from superset import db  # type: ignore[import-untyped]
        from superset.connectors.sqla.models import (  # type: ignore[import-untyped]
            SqlaTable,
        )
        from superset.models.core import Database  # type: ignore[import-untyped]
        from superset.models.dashboard import (  # type: ignore[import-untyped]
            Dashboard,
        )
        from superset.models.slice import Slice  # type: ignore[import-untyped]

        # ── 1. Database connection ──────────────────────────────────
        db_name = "Robot Framework Results"
        database = db.session.query(Database).filter_by(database_name=db_name).first()
        if database is None:
            database = Database(
                database_name=db_name,
                sqlalchemy_uri="postgresql://rfc:rfc@postgres:5432/rfc",
                expose_in_sqllab=True,
            )
            db.session.add(database)
            db.session.flush()
            log.info("Created database connection: %s", db_name)
        else:
            log.info("Database connection already exists: %s", db_name)

        # ── 2. Datasets ────────────────────────────────────────────
        datasets = {}
        for table_name in ("test_runs", "test_results", "models"):
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
                        "gitlab_branch",
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

        import json

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
            # Build a simple grid layout: 2 columns
            position_json = {}
            for i, slc in enumerate(slices):
                comp_id = f"CHART-{slc.id}"
                position_json[comp_id] = {
                    "type": "CHART",
                    "id": comp_id,
                    "children": [],
                    "meta": {
                        "width": 6,
                        "height": 50,
                        "chartId": slc.id,
                        "sliceName": slc.slice_name,
                    },
                }

            dashboard = Dashboard(
                dashboard_title=dash_title,
                slug="rfc-results",
                position_json=json.dumps(position_json),
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
