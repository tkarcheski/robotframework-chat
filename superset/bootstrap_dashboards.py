"""Bootstrap Superset with Robot Framework test result dashboards.

Run inside the Superset container after ``superset init`` to create:
  - The 4 PostgreSQL tables
    (``test_runs``, ``test_results``, ``test_run_artifacts``,
    ``test_result_artifacts``) plus ``coverage_reports``
  - A database connection to the RFC PostgreSQL tables
  - Virtual datasets for KPIs, host health, model performance
  - Charts covering KPIs, host health, model performance, git/version context
  - One consolidated dashboard: RFC Test Health
  - The Agentic Stack Tracker schema (``agentic_harnesses``,
    ``agentic_plugins``, ``agentic_skills``, ``agentic_metrics``,
    ``agentic_decisions``, ``dialog_recordings``, ``dialog_turns``), the
    ``agentic_sessions_full`` view, and the "Agentic Stack Tracker"
    dashboard (issue #353)

Lean schema: the two primary tables store only metrics; heavy data
(output.xml gzip, question/answer/grading/thinking text) lives in the
``*_artifacts`` tables and is exposed to Superset via the
``test_results_full`` view (LEFT JOIN).
"""

import json
import logging
import os
import sys
from typing import Any

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL DDL — lean test_runs/test_results + archive tables.
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

-- The view joins columns we are about to drop, take it down first.
DROP VIEW IF EXISTS test_results_full;

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
    session_id TEXT,
    model_harness TEXT
);

-- Issue #350: ensure session_id is present on upgrading databases.
ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS session_id TEXT;

-- Issue #350: ensure model_harness is present on upgrading databases.
ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS model_harness TEXT;

-- Databases predating the watermark 5-tuple lack a hostname column. The
-- test_results_full view below selects r.hostname, so add it on upgrade.
ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS hostname VARCHAR(255);

-- Drop columns that moved to the archive table on upgrading databases.
ALTER TABLE test_runs DROP COLUMN IF EXISTS output_xml_gz;
ALTER TABLE test_runs DROP COLUMN IF EXISTS output_xml_url;
ALTER TABLE test_runs DROP COLUMN IF EXISTS output_xml_source;
ALTER TABLE test_runs DROP COLUMN IF EXISTS temperature;
ALTER TABLE test_runs DROP COLUMN IF EXISTS seed;
ALTER TABLE test_runs DROP COLUMN IF EXISTS top_p;
ALTER TABLE test_runs DROP COLUMN IF EXISTS top_k;

CREATE TABLE IF NOT EXISTS test_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    test_name VARCHAR(500) NOT NULL,
    test_status VARCHAR(20) NOT NULL,
    score DOUBLE PRECISION,
    tags TEXT,
    tag_severity VARCHAR(20),
    tag_tier INTEGER,
    tag_verify VARCHAR(50),
    eval_count INTEGER,
    thinking_tokens INTEGER
);

-- Drop heavy text / unused numeric columns that moved to test_result_artifacts
-- or were never analyzed.
ALTER TABLE test_results DROP COLUMN IF EXISTS question;
ALTER TABLE test_results DROP COLUMN IF EXISTS expected_answer;
ALTER TABLE test_results DROP COLUMN IF EXISTS actual_answer;
ALTER TABLE test_results DROP COLUMN IF EXISTS grading_reason;
ALTER TABLE test_results DROP COLUMN IF EXISTS thinking_text;
ALTER TABLE test_results DROP COLUMN IF EXISTS rfc_version;
ALTER TABLE test_results DROP COLUMN IF EXISTS reasoning_tokens;
ALTER TABLE test_results DROP COLUMN IF EXISTS cached_tokens;
ALTER TABLE test_results DROP COLUMN IF EXISTS accepted_prediction_tokens;
ALTER TABLE test_results DROP COLUMN IF EXISTS rejected_prediction_tokens;
ALTER TABLE test_results DROP COLUMN IF EXISTS num_ctx;
ALTER TABLE test_results DROP COLUMN IF EXISTS num_predict;
ALTER TABLE test_results DROP COLUMN IF EXISTS eval_duration_ns;
ALTER TABLE test_results DROP COLUMN IF EXISTS prompt_eval_count;
ALTER TABLE test_results DROP COLUMN IF EXISTS prompt_eval_duration_ns;
ALTER TABLE test_results DROP COLUMN IF EXISTS load_duration_ns;
ALTER TABLE test_results DROP COLUMN IF EXISTS total_duration_ns;
ALTER TABLE test_results DROP COLUMN IF EXISTS tokens_per_second;
ALTER TABLE test_results DROP COLUMN IF EXISTS token_retry_count;
ALTER TABLE test_results DROP COLUMN IF EXISTS token_retry_max_tokens;

CREATE INDEX IF NOT EXISTS idx_test_runs_model ON test_runs(model_name);
CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp);
CREATE INDEX IF NOT EXISTS idx_test_runs_suite ON test_runs(test_suite);
CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);

ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tags TEXT;
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_severity VARCHAR(20);
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_tier INTEGER;
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_verify VARCHAR(50);
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS eval_count INTEGER;
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS thinking_tokens INTEGER;

-- Archive tables — heavy per-run / per-result data lives here.
CREATE TABLE IF NOT EXISTS test_run_artifacts (
    run_id INTEGER PRIMARY KEY REFERENCES test_runs(id) ON DELETE CASCADE,
    output_xml_gz BYTEA,
    output_xml_source TEXT
);

CREATE TABLE IF NOT EXISTS test_result_artifacts (
    result_id INTEGER PRIMARY KEY REFERENCES test_results(id) ON DELETE CASCADE,
    question TEXT,
    expected_answer TEXT,
    actual_answer TEXT,
    grading_reason TEXT,
    thinking_text TEXT
);

CREATE TABLE IF NOT EXISTS coverage_reports (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    git_commit VARCHAR(255) NOT NULL DEFAULT '',
    git_branch VARCHAR(255) NOT NULL DEFAULT '',
    hostname VARCHAR(255) NOT NULL DEFAULT '',
    rfc_version VARCHAR(50) NOT NULL DEFAULT '',
    total_statements INTEGER NOT NULL DEFAULT 0,
    total_missed INTEGER NOT NULL DEFAULT 0,
    total_covered INTEGER NOT NULL DEFAULT 0,
    coverage_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    module_name VARCHAR(500) NOT NULL DEFAULT '',
    module_statements INTEGER NOT NULL DEFAULT 0,
    module_missed INTEGER NOT NULL DEFAULT 0,
    module_covered INTEGER NOT NULL DEFAULT 0,
    module_coverage_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_coverage_reports_timestamp
    ON coverage_reports(timestamp);
CREATE INDEX IF NOT EXISTS idx_coverage_reports_git_commit
    ON coverage_reports(git_commit);

CREATE OR REPLACE VIEW test_results_full AS
SELECT
    tr.id AS result_id,
    tr.run_id,
    tr.test_name,
    tr.test_status,
    tr.score,
    tr.tags,
    tr.tag_severity,
    tr.tag_tier,
    tr.tag_verify,
    tr.eval_count,
    tr.thinking_tokens,
    r.timestamp,
    r.model_name,
    r.test_suite,
    r.total_tests,
    r.passed,
    r.failed,
    r.skipped,
    r.duration_seconds,
    r.git_commit,
    r.git_branch,
    r.hostname,
    r.rfc_version,
    r.session_id,
    r.model_harness,
    ra.output_xml_source,
    rsa.question,
    rsa.expected_answer,
    rsa.actual_answer,
    rsa.grading_reason,
    rsa.thinking_text
FROM test_results tr
JOIN test_runs r ON tr.run_id = r.id
LEFT JOIN test_run_artifacts ra ON ra.run_id = r.id
LEFT JOIN test_result_artifacts rsa ON rsa.result_id = tr.id;
"""

# ---------------------------------------------------------------------------
# Status colors — consistent across all charts.
# ---------------------------------------------------------------------------
STATUS_COLORS: dict[str, str] = {
    "PASS": "#2ECC71",
    "FAIL": "#E74C3C",
    "ERROR": "#E74C3C",
    "SKIP": "#95A5A6",
}

# Threshold for pass-rate alerting (percent).
PASS_RATE_THRESHOLD = 95.0

# ---------------------------------------------------------------------------
# Virtual datasets — SQL for computed views.
# ---------------------------------------------------------------------------
_VIRTUAL_DATASETS: dict[str, str] = {
    "kpi_overall_pass_rate": """
        SELECT
            ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)
                AS pass_rate_pct,
            SUM(total_tests) AS total_tests,
            SUM(passed) AS total_passed,
            SUM(failed) AS total_failed
        FROM test_runs
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
    """,
    "kpi_failing_hosts": """
        SELECT
            hostname,
            ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)
                AS pass_rate_pct
        FROM test_runs
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY hostname
        HAVING 100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0) < 95
    """,
    "kpi_slowest_host": """
        SELECT
            hostname,
            PERCENTILE_CONT(0.5)
                WITHIN GROUP (ORDER BY duration_seconds) AS median_runtime
        FROM test_runs
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY hostname
        ORDER BY median_runtime DESC
        LIMIT 1
    """,
    "kpi_worst_model": """
        SELECT
            model_name,
            ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)
                AS pass_rate_pct
        FROM test_runs
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY model_name
        ORDER BY pass_rate_pct ASC
        LIMIT 1
    """,
    "host_pass_rate_timeseries": """
        SELECT
            DATE_TRUNC('hour', timestamp) AS time_bucket,
            hostname,
            ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)
                AS pass_rate_pct,
            SUM(total_tests) AS total_tests,
            SUM(failed) AS total_failed
        FROM test_runs
        GROUP BY DATE_TRUNC('hour', timestamp), hostname
        ORDER BY time_bucket
    """,
    "host_current_pass_rate": """
        SELECT
            hostname,
            ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)
                AS pass_rate_pct,
            SUM(total_tests) AS total_tests,
            SUM(passed) AS total_passed,
            SUM(failed) AS total_failed,
            COUNT(*) AS run_count
        FROM test_runs
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY hostname
        ORDER BY pass_rate_pct ASC
    """,
    "model_runtime_percentiles": """
        SELECT
            model_name,
            COUNT(*) AS run_count,
            ROUND(PERCENTILE_CONT(0.25)
                WITHIN GROUP (ORDER BY duration_seconds)::numeric, 2)
                AS p25_runtime,
            ROUND(PERCENTILE_CONT(0.50)
                WITHIN GROUP (ORDER BY duration_seconds)::numeric, 2)
                AS p50_runtime,
            ROUND(PERCENTILE_CONT(0.75)
                WITHIN GROUP (ORDER BY duration_seconds)::numeric, 2)
                AS p75_runtime,
            ROUND(PERCENTILE_CONT(0.95)
                WITHIN GROUP (ORDER BY duration_seconds)::numeric, 2)
                AS p95_runtime,
            ROUND(AVG(duration_seconds)::numeric, 2) AS avg_runtime
        FROM test_runs
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY model_name
    """,
    "model_pass_rate_timeseries": """
        SELECT
            DATE_TRUNC('hour', timestamp) AS time_bucket,
            model_name,
            ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)
                AS pass_rate_pct,
            SUM(total_tests) AS total_tests
        FROM test_runs
        GROUP BY DATE_TRUNC('hour', timestamp), model_name
        ORDER BY time_bucket
    """,
    "version_pass_rate": """
        SELECT
            COALESCE(rfc_version, 'unknown') AS rfc_version,
            ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)
                AS pass_rate_pct,
            SUM(total_tests) AS total_tests,
            COUNT(*) AS run_count
        FROM test_runs
        GROUP BY COALESCE(rfc_version, 'unknown')
        ORDER BY run_count DESC
    """,
    "host_recent_failures": """
        SELECT
            r.hostname,
            tr.test_name,
            tr.test_status,
            r.model_name,
            r.timestamp
        FROM test_results tr
        JOIN test_runs r ON tr.run_id = r.id
        WHERE tr.test_status IN ('FAIL', 'ERROR')
          AND r.timestamp >= NOW() - INTERVAL '24 hours'
        ORDER BY r.timestamp DESC
    """,
    # --- Flaky test detection (7-day window) ---
    "flaky_test_scores": """
        SELECT
            tr.test_name,
            r.model_name,
            COUNT(*) AS total_runs,
            SUM(CASE WHEN tr.test_status = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
            SUM(CASE WHEN tr.test_status = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
            ROUND(
                CASE WHEN COUNT(*) < 2 THEN 0.0
                ELSE 2.0
                    * SUM(CASE WHEN tr.test_status = 'PASS' THEN 1 ELSE 0 END)
                    * SUM(CASE WHEN tr.test_status = 'FAIL' THEN 1 ELSE 0 END)
                    / (COUNT(*) * COUNT(*))
                END::numeric, 3
            ) AS flaky_score
        FROM test_results tr
        JOIN test_runs r ON tr.run_id = r.id
        WHERE r.timestamp >= NOW() - INTERVAL '7 days'
          AND tr.test_status IN ('PASS', 'FAIL')
        GROUP BY tr.test_name, r.model_name
        HAVING COUNT(*) >= 2
        ORDER BY flaky_score DESC
    """,
    "flaky_test_summary": """
        SELECT
            tr.test_name,
            COUNT(*) AS total_runs,
            SUM(CASE WHEN tr.test_status = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
            SUM(CASE WHEN tr.test_status = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
            COUNT(DISTINCT r.model_name) AS model_count,
            ROUND(
                CASE WHEN COUNT(*) < 2 THEN 0.0
                ELSE 2.0
                    * SUM(CASE WHEN tr.test_status = 'PASS' THEN 1 ELSE 0 END)
                    * SUM(CASE WHEN tr.test_status = 'FAIL' THEN 1 ELSE 0 END)
                    / (COUNT(*) * COUNT(*))
                END::numeric, 3
            ) AS flaky_score
        FROM test_results tr
        JOIN test_runs r ON tr.run_id = r.id
        WHERE r.timestamp >= NOW() - INTERVAL '7 days'
          AND tr.test_status IN ('PASS', 'FAIL')
        GROUP BY tr.test_name
        HAVING COUNT(*) >= 2
        ORDER BY flaky_score DESC
    """,
    "flaky_trend_timeseries": """
        SELECT
            sub.time_bucket,
            COUNT(DISTINCT CASE
                WHEN sub.flaky_score > 0.1 THEN sub.test_name
            END) AS flaky_count,
            COUNT(DISTINCT sub.test_name) AS total_tests
        FROM (
            SELECT
                tr.test_name,
                DATE_TRUNC('day', r2.timestamp) AS time_bucket,
                CASE WHEN COUNT(*) < 2 THEN 0.0
                ELSE 2.0
                    * SUM(CASE WHEN tr.test_status = 'PASS' THEN 1 ELSE 0 END)
                    * SUM(CASE WHEN tr.test_status = 'FAIL' THEN 1 ELSE 0 END)
                    / (COUNT(*) * COUNT(*))
                END AS flaky_score
            FROM test_results tr
            JOIN test_runs r2 ON tr.run_id = r2.id
            WHERE tr.test_status IN ('PASS', 'FAIL')
            GROUP BY tr.test_name, DATE_TRUNC('day', r2.timestamp)
        ) sub
        GROUP BY sub.time_bucket
        ORDER BY time_bucket
    """,
    "kpi_flaky_test_count": """
        SELECT
            COUNT(*) AS flaky_count
        FROM (
            SELECT
                tr.test_name
            FROM test_results tr
            JOIN test_runs r ON tr.run_id = r.id
            WHERE r.timestamp >= NOW() - INTERVAL '7 days'
              AND tr.test_status IN ('PASS', 'FAIL')
            GROUP BY tr.test_name
            HAVING COUNT(*) >= 2
               AND 2.0
                   * SUM(CASE WHEN tr.test_status = 'PASS' THEN 1 ELSE 0 END)
                   * SUM(CASE WHEN tr.test_status = 'FAIL' THEN 1 ELSE 0 END)
                   / (COUNT(*) * COUNT(*)) > 0.1
        ) flaky_tests
    """,
    # --- Coverage datasets ---
    "kpi_current_coverage": """
        SELECT
            ROUND(AVG(coverage_pct)::numeric, 1) AS coverage_pct,
            SUM(total_statements) AS total_statements,
            SUM(total_covered) AS total_covered,
            SUM(total_missed) AS total_missed
        FROM coverage_reports
        WHERE module_name = ''
          AND timestamp = (
              SELECT MAX(timestamp)
              FROM coverage_reports
              WHERE module_name = ''
          )
    """,
    "coverage_timeseries": """
        SELECT
            DATE_TRUNC('day', timestamp) AS time_bucket,
            ROUND(AVG(coverage_pct)::numeric, 1) AS coverage_pct,
            SUM(total_statements) AS total_statements,
            SUM(total_covered) AS total_covered
        FROM coverage_reports
        WHERE module_name = ''
        GROUP BY DATE_TRUNC('day', timestamp)
        ORDER BY time_bucket
    """,
    "coverage_by_module": """
        SELECT
            module_name,
            ROUND(AVG(module_coverage_pct)::numeric, 1) AS module_coverage_pct,
            AVG(module_statements)::integer AS module_statements,
            AVG(module_covered)::integer AS module_covered,
            AVG(module_missed)::integer AS module_missed
        FROM coverage_reports
        WHERE module_name != ''
          AND timestamp = (
              SELECT MAX(timestamp) FROM coverage_reports
          )
        GROUP BY module_name
        ORDER BY module_coverage_pct ASC
    """,
    # --- Token efficiency datasets ---
    "kpi_avg_tokens_per_correct": """
        SELECT
            ROUND(AVG(tr.eval_count)::numeric, 1) AS avg_tokens_per_correct,
            COUNT(*) AS correct_count,
            SUM(tr.eval_count) AS total_tokens
        FROM test_results tr
        JOIN test_runs r ON tr.run_id = r.id
        WHERE tr.score >= 0.5
          AND tr.eval_count > 0
          AND r.timestamp >= NOW() - INTERVAL '24 hours'
    """,
    "model_token_efficiency": """
        SELECT
            r.model_name,
            COUNT(*) AS correct_count,
            ROUND(AVG(tr.eval_count)::numeric, 1) AS avg_tokens_per_correct,
            ROUND(PERCENTILE_CONT(0.5)
                WITHIN GROUP (ORDER BY tr.eval_count)::numeric, 1)
                AS median_tokens_per_correct,
            MIN(tr.eval_count) AS min_tokens,
            MAX(tr.eval_count) AS max_tokens
        FROM test_results tr
        JOIN test_runs r ON tr.run_id = r.id
        WHERE tr.score >= 0.5
          AND tr.eval_count > 0
          AND r.timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY r.model_name
        ORDER BY avg_tokens_per_correct ASC
    """,
    "token_efficiency_timeseries": """
        SELECT
            DATE_TRUNC('hour', r.timestamp) AS time_bucket,
            r.model_name,
            ROUND(AVG(tr.eval_count)::numeric, 1) AS avg_tokens_per_correct,
            COUNT(*) AS correct_count
        FROM test_results tr
        JOIN test_runs r ON tr.run_id = r.id
        WHERE tr.score >= 0.5
          AND tr.eval_count > 0
        GROUP BY DATE_TRUNC('hour', r.timestamp), r.model_name
        ORDER BY time_bucket
    """,
    "coverage_by_commit": """
        SELECT
            git_commit,
            git_branch,
            timestamp,
            ROUND(coverage_pct::numeric, 1) AS coverage_pct,
            total_statements,
            total_covered,
            total_missed
        FROM coverage_reports
        WHERE module_name = ''
        ORDER BY timestamp DESC
        LIMIT 50
    """,
}

# ---------------------------------------------------------------------------
# Chart definitions — datasource_id_key maps to dataset name at runtime.
# ---------------------------------------------------------------------------
_CHART_DEFS: list[dict[str, Any]] = [
    # --- KPI Row ---
    {
        "slice_name": "Overall Pass Rate (24h)",
        "viz_type": "big_number_total",
        "datasource_id_key": "kpi_overall_pass_rate",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "pass_rate_pct"},
                "aggregate": "MAX",
                "label": "Pass Rate %",
            },
            "subheader": "Last 24 hours",
            "y_axis_format": ".1f",
            "conditional_formatting": [
                {
                    "operator": ">=",
                    "targetValue": PASS_RATE_THRESHOLD,
                    "color": STATUS_COLORS["PASS"],
                },
                {
                    "operator": "<",
                    "targetValue": PASS_RATE_THRESHOLD,
                    "color": STATUS_COLORS["FAIL"],
                },
            ],
        },
    },
    {
        "slice_name": "Failing Hosts",
        "viz_type": "big_number_total",
        "datasource_id_key": "kpi_failing_hosts",
        "params": {
            "metric": {
                "expressionType": "SQL",
                "sqlExpression": "COUNT(*)",
                "label": "Failing Hosts",
            },
            "subheader": f"Pass rate < {PASS_RATE_THRESHOLD}%",
            "conditional_formatting": [
                {
                    "operator": ">",
                    "targetValue": 0,
                    "color": STATUS_COLORS["FAIL"],
                },
                {
                    "operator": "==",
                    "targetValue": 0,
                    "color": STATUS_COLORS["PASS"],
                },
            ],
        },
    },
    {
        "slice_name": "Slowest Host",
        "viz_type": "big_number_total",
        "datasource_id_key": "kpi_slowest_host",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "median_runtime"},
                "aggregate": "MAX",
                "label": "Median Runtime (s)",
            },
            "subheader": "Slowest host by median duration",
            "y_axis_format": ".1f",
        },
    },
    {
        "slice_name": "Worst Model Today",
        "viz_type": "big_number_total",
        "datasource_id_key": "kpi_worst_model",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "pass_rate_pct"},
                "aggregate": "MIN",
                "label": "Worst Pass Rate %",
            },
            "subheader": "Lowest pass rate model (24h)",
            "y_axis_format": ".1f",
            "conditional_formatting": [
                {
                    "operator": "<",
                    "targetValue": PASS_RATE_THRESHOLD,
                    "color": STATUS_COLORS["FAIL"],
                },
            ],
        },
    },
    # --- Host Health Section ---
    {
        "slice_name": "Host Pass Rate Over Time",
        "viz_type": "echarts_timeseries_line",
        "datasource_id_key": "host_pass_rate_timeseries",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "pass_rate_pct"},
                    "aggregate": "AVG",
                    "label": "Pass Rate %",
                },
            ],
            "groupby": ["hostname"],
            "x_axis": "time_bucket",
            "granularity_sqla": "time_bucket",
            "rolling_type": "mean",
            "rolling_periods": 6,
            "y_axis_bounds": [0, 100],
            "annotation_layers": [
                {
                    "name": f"{PASS_RATE_THRESHOLD}% Threshold",
                    "annotationType": "FORMULA",
                    "value": str(PASS_RATE_THRESHOLD),
                    "style": "dashed",
                    "color": STATUS_COLORS["FAIL"],
                },
            ],
        },
    },
    {
        "slice_name": "Current Pass Rate by Host",
        "viz_type": "echarts_bar",
        "datasource_id_key": "host_current_pass_rate",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "pass_rate_pct"},
                    "aggregate": "MAX",
                    "label": "Pass Rate %",
                },
            ],
            "groupby": ["hostname"],
            "order_desc": False,
            "y_axis_bounds": [0, 100],
            "conditional_formatting": [
                {
                    "operator": "<",
                    "targetValue": 90.0,
                    "color": STATUS_COLORS["FAIL"],
                },
                {
                    "operator": "<",
                    "targetValue": PASS_RATE_THRESHOLD,
                    "color": "#F39C12",
                },
            ],
        },
    },
    {
        "slice_name": "Recent Failures by Host",
        "viz_type": "echarts_bar",
        "datasource_id_key": "host_recent_failures",
        "params": {
            "metrics": [
                {
                    "expressionType": "SQL",
                    "sqlExpression": "COUNT(*)",
                    "label": "Failure Count",
                },
            ],
            "groupby": ["hostname"],
            "color_scheme": "supersetColors",
            "series_colors": {"Failure Count": STATUS_COLORS["FAIL"]},
        },
    },
    # --- Model Performance Section ---
    {
        "slice_name": "Pass Trends by Model",
        "viz_type": "echarts_timeseries_line",
        "datasource_id_key": "model_pass_rate_timeseries",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "pass_rate_pct"},
                    "aggregate": "AVG",
                    "label": "Pass Rate %",
                },
            ],
            "groupby": ["model_name"],
            "x_axis": "time_bucket",
            "granularity_sqla": "time_bucket",
            "rolling_type": "mean",
            "rolling_periods": 6,
            "y_axis_bounds": [0, 100],
        },
    },
    {
        "slice_name": "Model Runtime Distribution",
        "viz_type": "echarts_bar",
        "datasource_id_key": "model_runtime_percentiles",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "p25_runtime"},
                    "aggregate": "MAX",
                    "label": "P25",
                },
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "p50_runtime"},
                    "aggregate": "MAX",
                    "label": "P50 (Median)",
                },
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "p75_runtime"},
                    "aggregate": "MAX",
                    "label": "P75",
                },
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "p95_runtime"},
                    "aggregate": "MAX",
                    "label": "P95",
                },
            ],
            "groupby": ["model_name"],
        },
    },
    {
        "slice_name": "Model Comparison \u2014 Pass Rate",
        "viz_type": "echarts_bar",
        "datasource_id_key": "test_runs",
        "params": {
            "metrics": [
                {
                    "expressionType": "SQL",
                    "sqlExpression": (
                        "ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)"
                    ),
                    "label": "Pass Rate %",
                },
            ],
            "groupby": ["model_name"],
            "order_desc": True,
            "y_axis_bounds": [0, 100],
        },
    },
    # --- Token Efficiency Section ---
    {
        "slice_name": "Avg Tokens/Correct (24h)",
        "viz_type": "big_number_total",
        "datasource_id_key": "kpi_avg_tokens_per_correct",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "avg_tokens_per_correct"},
                "aggregate": "MAX",
                "label": "Avg Tokens",
            },
            "subheader": "Mean response tokens for correct answers (24h)",
            "y_axis_format": ".0f",
        },
    },
    {
        "slice_name": "Model Token Efficiency",
        "viz_type": "echarts_bar",
        "datasource_id_key": "model_token_efficiency",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "avg_tokens_per_correct"},
                    "aggregate": "MAX",
                    "label": "Avg Tokens/Correct",
                },
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "median_tokens_per_correct"},
                    "aggregate": "MAX",
                    "label": "Median Tokens/Correct",
                },
            ],
            "groupby": ["model_name"],
            "order_desc": False,
        },
    },
    {
        "slice_name": "Token Efficiency Trend",
        "viz_type": "echarts_timeseries_line",
        "datasource_id_key": "token_efficiency_timeseries",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "avg_tokens_per_correct"},
                    "aggregate": "AVG",
                    "label": "Avg Tokens/Correct",
                },
            ],
            "groupby": ["model_name"],
            "x_axis": "time_bucket",
            "granularity_sqla": "time_bucket",
        },
    },
    # --- Git / Version Context ---
    {
        "slice_name": "RFC Version Distribution",
        "viz_type": "pie",
        "datasource_id_key": "version_pass_rate",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "run_count"},
                    "aggregate": "MAX",
                    "label": "Run Count",
                },
            ],
            "groupby": ["rfc_version"],
            "row_limit": 10,
        },
    },
    {
        "slice_name": "Pass Rate by RFC Version",
        "viz_type": "echarts_timeseries_line",
        "datasource_id_key": "test_runs",
        "params": {
            "metrics": [
                {
                    "expressionType": "SQL",
                    "sqlExpression": (
                        "ROUND(100.0 * SUM(passed) / NULLIF(SUM(total_tests), 0), 1)"
                    ),
                    "label": "Pass Rate %",
                },
            ],
            "groupby": ["rfc_version"],
            "time_column": "timestamp",
            "granularity_sqla": "timestamp",
            "y_axis_bounds": [0, 100],
        },
    },
    # --- Status Breakdown ---
    {
        "slice_name": "Test Status Breakdown",
        "viz_type": "pie",
        "datasource_id_key": "test_results_full",
        "params": {
            "metrics": [
                {
                    "expressionType": "SQL",
                    "sqlExpression": "COUNT(*)",
                    "label": "Count",
                },
            ],
            "groupby": ["test_status"],
            "color_map": STATUS_COLORS,
        },
    },
    # --- Drill-Down Tables ---
    {
        "slice_name": "Recent Test Runs",
        "viz_type": "table",
        "datasource_id_key": "test_runs",
        "params": {
            "columns": [
                "timestamp",
                "hostname",
                "model_name",
                "rfc_version",
                "test_suite",
                "passed",
                "failed",
                "skipped",
                "duration_seconds",
                "git_branch",
            ],
            "order_desc": True,
            "row_limit": 100,
        },
    },
    {
        "slice_name": "Test Results Detail",
        "viz_type": "table",
        "datasource_id_key": "test_results_full",
        "params": {
            "columns": [
                "timestamp",
                "hostname",
                "model_name",
                "rfc_version",
                "test_suite",
                "test_name",
                "test_status",
                "duration_seconds",
                "score",
                "grading_reason",
            ],
            "order_desc": True,
            "row_limit": 200,
        },
    },
]

# ---------------------------------------------------------------------------
# Native filter configurations — wired to all charts.
# ---------------------------------------------------------------------------
_FILTER_CONFIGS: list[dict[str, Any]] = [
    {
        "id": "NATIVE_FILTER-TIME",
        "name": "Time Range",
        "filterType": "filter_time",
        "targets": [{"datasetId": "__TEST_RUNS_ID__"}],
        "defaultDataMask": {"filterState": {"value": "Last day"}},
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "NATIVE_FILTER-HOST",
        "name": "Host",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "hostname"},
                "datasetId": "__TEST_RUNS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "NATIVE_FILTER-MODEL",
        "name": "Model",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "model_name"},
                "datasetId": "__TEST_RUNS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "NATIVE_FILTER-VERSION",
        "name": "RFC Version",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "rfc_version"},
                "datasetId": "__TEST_RUNS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
]

# ---------------------------------------------------------------------------
# Dashboard layout sections — maps chart names to grid positions.
# Superset uses a 12-column grid.  height is in grid units (1 unit ~ 8px).
# ---------------------------------------------------------------------------
_LAYOUT_SECTIONS: list[dict[str, Any]] = [
    {
        "label": "KPI Row",
        "charts": [
            {"name": "Overall Pass Rate (24h)", "width": 3, "height": 10},
            {"name": "Failing Hosts", "width": 3, "height": 10},
            {"name": "Slowest Host", "width": 3, "height": 10},
            {"name": "Worst Model Today", "width": 3, "height": 10},
        ],
    },
    {
        "label": "Host Health",
        "charts": [
            {"name": "Host Pass Rate Over Time", "width": 8, "height": 50},
            {"name": "Current Pass Rate by Host", "width": 4, "height": 50},
        ],
    },
    {
        "label": "Host Failures",
        "charts": [
            {"name": "Recent Failures by Host", "width": 6, "height": 40},
            {"name": "Test Status Breakdown", "width": 6, "height": 40},
        ],
    },
    {
        "label": "Model Performance",
        "charts": [
            {"name": "Pass Trends by Model", "width": 6, "height": 50},
            {"name": "Model Runtime Distribution", "width": 6, "height": 50},
        ],
    },
    {
        "label": "Model Comparison",
        "charts": [
            {"name": "Model Comparison \u2014 Pass Rate", "width": 12, "height": 40},
        ],
    },
    {
        "label": "Token Efficiency",
        "charts": [
            {"name": "Avg Tokens/Correct (24h)", "width": 3, "height": 10},
            {"name": "Model Token Efficiency", "width": 9, "height": 50},
        ],
    },
    {
        "label": "Token Efficiency Trends",
        "charts": [
            {"name": "Token Efficiency Trend", "width": 12, "height": 50},
        ],
    },
    {
        "label": "Git / Version Context",
        "charts": [
            {"name": "RFC Version Distribution", "width": 4, "height": 40},
            {"name": "Pass Rate by RFC Version", "width": 8, "height": 40},
        ],
    },
    {
        "label": "Drill-Down",
        "charts": [
            {"name": "Recent Test Runs", "width": 12, "height": 50},
            {"name": "Test Results Detail", "width": 12, "height": 50},
        ],
    },
]


# ---------------------------------------------------------------------------
# Test Infrastructure Dashboard — flaky detection + coverage
# ---------------------------------------------------------------------------

_INFRA_CHART_DEFS: list[dict[str, Any]] = [
    # --- Flaky KPI Row ---
    {
        "slice_name": "Flaky Tests (7d)",
        "viz_type": "big_number_total",
        "datasource_id_key": "kpi_flaky_test_count",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "flaky_count"},
                "aggregate": "MAX",
                "label": "Flaky Tests",
            },
            "subheader": "Tests with flaky_score > 0.1 (7 days)",
            "conditional_formatting": [
                {
                    "operator": ">",
                    "targetValue": 0,
                    "color": STATUS_COLORS["FAIL"],
                },
                {
                    "operator": "==",
                    "targetValue": 0,
                    "color": STATUS_COLORS["PASS"],
                },
            ],
        },
    },
    {
        "slice_name": "Flakiest Test",
        "viz_type": "big_number_total",
        "datasource_id_key": "flaky_test_summary",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "flaky_score"},
                "aggregate": "MAX",
                "label": "Worst Flaky Score",
            },
            "subheader": "Highest flaky score (0=stable, 1=random)",
            "y_axis_format": ".3f",
            "conditional_formatting": [
                {
                    "operator": ">=",
                    "targetValue": 0.5,
                    "color": STATUS_COLORS["FAIL"],
                },
                {
                    "operator": ">=",
                    "targetValue": 0.1,
                    "color": "#F39C12",
                },
            ],
        },
    },
    # --- Flaky Detail ---
    {
        "slice_name": "Flaky Test Scores",
        "viz_type": "echarts_bar",
        "datasource_id_key": "flaky_test_scores",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "flaky_score"},
                    "aggregate": "MAX",
                    "label": "Flaky Score",
                },
            ],
            "groupby": ["test_name"],
            "order_desc": True,
            "row_limit": 20,
            "y_axis_bounds": [0, 1],
            "color_scheme": "supersetColors",
        },
    },
    {
        "slice_name": "Flaky Trend Over Time",
        "viz_type": "echarts_timeseries_line",
        "datasource_id_key": "flaky_trend_timeseries",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "flaky_count"},
                    "aggregate": "MAX",
                    "label": "Flaky Test Count",
                },
            ],
            "x_axis": "time_bucket",
            "granularity_sqla": "time_bucket",
        },
    },
    {
        "slice_name": "Flaky Tests Detail",
        "viz_type": "table",
        "datasource_id_key": "flaky_test_scores",
        "params": {
            "columns": [
                "test_name",
                "model_name",
                "total_runs",
                "pass_count",
                "fail_count",
                "flaky_score",
            ],
            "order_desc": True,
            "row_limit": 50,
        },
    },
    # --- Coverage KPI Row ---
    {
        "slice_name": "Current Coverage %",
        "viz_type": "big_number_total",
        "datasource_id_key": "kpi_current_coverage",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "coverage_pct"},
                "aggregate": "MAX",
                "label": "Coverage %",
            },
            "subheader": "Latest pytest-cov result",
            "y_axis_format": ".1f",
            "conditional_formatting": [
                {
                    "operator": ">=",
                    "targetValue": 80,
                    "color": STATUS_COLORS["PASS"],
                },
                {
                    "operator": "<",
                    "targetValue": 80,
                    "color": STATUS_COLORS["FAIL"],
                },
            ],
        },
    },
    {
        "slice_name": "Coverage Delta (7d)",
        "viz_type": "big_number_total",
        "datasource_id_key": "coverage_timeseries",
        "params": {
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "coverage_pct"},
                "aggregate": "MAX",
                "label": "Coverage %",
            },
            "subheader": "Coverage trend over 7 days",
            "y_axis_format": ".1f",
        },
    },
    # --- Coverage Detail ---
    {
        "slice_name": "Coverage Over Time",
        "viz_type": "echarts_timeseries_line",
        "datasource_id_key": "coverage_timeseries",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "coverage_pct"},
                    "aggregate": "AVG",
                    "label": "Coverage %",
                },
            ],
            "x_axis": "time_bucket",
            "granularity_sqla": "time_bucket",
            "y_axis_bounds": [0, 100],
            "annotation_layers": [
                {
                    "name": "80% Target",
                    "annotationType": "FORMULA",
                    "value": "80",
                    "style": "dashed",
                    "color": STATUS_COLORS["PASS"],
                },
            ],
        },
    },
    {
        "slice_name": "Coverage by Module",
        "viz_type": "echarts_bar",
        "datasource_id_key": "coverage_by_module",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "module_coverage_pct"},
                    "aggregate": "MAX",
                    "label": "Coverage %",
                },
            ],
            "groupby": ["module_name"],
            "order_desc": False,
            "y_axis_bounds": [0, 100],
        },
    },
    {
        "slice_name": "Coverage by Commit",
        "viz_type": "table",
        "datasource_id_key": "coverage_by_commit",
        "params": {
            "columns": [
                "timestamp",
                "git_commit",
                "git_branch",
                "coverage_pct",
                "total_statements",
                "total_covered",
                "total_missed",
            ],
            "order_desc": True,
            "row_limit": 50,
        },
    },
]

_INFRA_FILTER_CONFIGS: list[dict[str, Any]] = [
    {
        "id": "INFRA_FILTER-TIME",
        "name": "Time Range",
        "filterType": "filter_time",
        "targets": [{"datasetId": "__TEST_RUNS_ID__"}],
        "defaultDataMask": {"filterState": {"value": "Last week"}},
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "INFRA_FILTER-MODEL",
        "name": "Model",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "model_name"},
                "datasetId": "__TEST_RUNS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "INFRA_FILTER-SUITE",
        "name": "Test Suite",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "test_suite"},
                "datasetId": "__TEST_RUNS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
]

_INFRA_LAYOUT_SECTIONS: list[dict[str, Any]] = [
    {
        "label": "Flaky Detection",
        "charts": [
            {"name": "Flaky Tests (7d)", "width": 6, "height": 10},
            {"name": "Flakiest Test", "width": 6, "height": 10},
        ],
    },
    {
        "label": "Flaky Analysis",
        "charts": [
            {"name": "Flaky Test Scores", "width": 6, "height": 50},
            {"name": "Flaky Trend Over Time", "width": 6, "height": 50},
        ],
    },
    {
        "label": "Flaky Detail",
        "charts": [
            {"name": "Flaky Tests Detail", "width": 12, "height": 50},
        ],
    },
    {
        "label": "Coverage KPIs",
        "charts": [
            {"name": "Current Coverage %", "width": 6, "height": 10},
            {"name": "Coverage Delta (7d)", "width": 6, "height": 10},
        ],
    },
    {
        "label": "Coverage Trends",
        "charts": [
            {"name": "Coverage Over Time", "width": 8, "height": 50},
            {"name": "Coverage by Module", "width": 4, "height": 50},
        ],
    },
    {
        "label": "Coverage History",
        "charts": [
            {"name": "Coverage by Commit", "width": 12, "height": 50},
        ],
    },
]


# ---------------------------------------------------------------------------
# Agentic Stack Tracker dashboard (issue #353)
# ---------------------------------------------------------------------------

# DDL for the agentic stack tables (canonical schema lives in
# src/rfc/harness_db.py — the HarnessDatabase backends create the same
# tables with IF NOT EXISTS, so either side may run first) plus the
# ``agentic_sessions_full`` view. The view body is a copy of
# rfc.harness_db.AGENTIC_SESSIONS_FULL_VIEW_BODY; a drift-guard test in
# tests/test_bootstrap_dashboards.py keeps the two in sync. Written in the
# portable subset shared by PostgreSQL and SQLite (DROP VIEW IF EXISTS +
# CREATE VIEW instead of CREATE OR REPLACE) so tests can prove idempotency.
_AGENTIC_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS agentic_harnesses (
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
);
CREATE INDEX IF NOT EXISTS idx_harnesses_tool ON agentic_harnesses(tool_name);

CREATE TABLE IF NOT EXISTS agentic_plugins (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    plugin_name     TEXT NOT NULL,
    semver          TEXT,
    source          TEXT,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id)
        REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE,
    UNIQUE (session_id, plugin_name)
);
CREATE INDEX IF NOT EXISTS idx_plugins_session ON agentic_plugins(session_id);

CREATE TABLE IF NOT EXISTS agentic_skills (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    skill_path      TEXT NOT NULL,
    git_sha         TEXT,
    skill_name      TEXT,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id)
        REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE,
    UNIQUE (session_id, skill_path)
);
CREATE INDEX IF NOT EXISTS idx_skills_session ON agentic_skills(session_id);

CREATE TABLE IF NOT EXISTS agentic_metrics (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    test_run_id     INTEGER,
    test_result_id  INTEGER,
    metric_key      TEXT NOT NULL,
    metric_value    REAL,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id)
        REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_metrics_session ON agentic_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_metrics_key     ON agentic_metrics(metric_key);
CREATE INDEX IF NOT EXISTS idx_metrics_run     ON agentic_metrics(test_run_id);

CREATE TABLE IF NOT EXISTS agentic_decisions (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    test_name       TEXT,
    hook_event      TEXT NOT NULL,
    prompt_model    TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    response_text   TEXT,
    proposed_action TEXT,
    applied         INTEGER NOT NULL,
    tokens_used     INTEGER,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id)
        REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_decisions_session
    ON agentic_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action
    ON agentic_decisions(proposed_action);

CREATE TABLE IF NOT EXISTS dialog_recordings (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    source_type     TEXT NOT NULL,
    tool_name       TEXT,
    tool_version    TEXT,
    model_id        TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    metadata_json   TEXT,
    FOREIGN KEY (session_id)
        REFERENCES agentic_harnesses(session_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS dialog_turns (
    id                  TEXT PRIMARY KEY,
    recording_id        TEXT NOT NULL,
    turn_number         INTEGER NOT NULL,
    role                TEXT NOT NULL,
    content             TEXT,
    tool_calls_json     TEXT,
    tool_results_json   TEXT,
    timestamp           TEXT NOT NULL,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    latency_ms          REAL,
    FOREIGN KEY (recording_id)
        REFERENCES dialog_recordings(id) ON DELETE CASCADE,
    UNIQUE (recording_id, turn_number)
);
CREATE INDEX IF NOT EXISTS idx_dialog_turns_recording
    ON dialog_turns(recording_id);

DROP VIEW IF EXISTS agentic_sessions_full;

CREATE VIEW agentic_sessions_full AS
SELECT
    h.session_id,
    h.tool_name,
    h.tool_version,
    h.model_id,
    h.rfc_version,
    h.branch,
    h.started_at,
    CAST(h.started_at AS TIMESTAMP) AS started_ts,
    h.ended_at,
    h.outcome,
    h.replay_of_recording_id,
    SUM(CASE WHEN m.metric_key = 'tokens_in' THEN m.metric_value END)
        AS tokens_in,
    SUM(CASE WHEN m.metric_key = 'tokens_out' THEN m.metric_value END)
        AS tokens_out,
    AVG(CASE WHEN m.metric_key = 'latency_ms' THEN m.metric_value END)
        AS avg_latency_ms,
    AVG(CASE WHEN m.metric_key = 'grader_score' THEN m.metric_value END)
        AS avg_grader_score
FROM agentic_harnesses h
LEFT JOIN agentic_metrics m ON m.session_id = h.session_id
GROUP BY h.session_id, h.tool_name, h.tool_version, h.model_id,
         h.rfc_version, h.branch, h.started_at, h.ended_at, h.outcome,
         h.replay_of_recording_id;
"""

# Physical tables / views registered as Superset datasets.
_AGENTIC_DATASET_TABLES: list[str] = [
    "agentic_harnesses",
    "agentic_plugins",
    "agentic_skills",
    "agentic_metrics",
    "agentic_decisions",
    "agentic_sessions_full",
]

# Virtual datasets. Written in the PostgreSQL/SQLite-portable subset
# (window functions, no NOW()/DATE_TRUNC) so tests can probe them.
_AGENTIC_VIRTUAL_DATASETS: dict[str, str] = {
    "agentic_plugin_drift": """
        SELECT
            p.recorded_at,
            h.tool_name,
            h.model_id,
            h.outcome,
            h.rfc_version,
            p.plugin_name,
            p.semver,
            LAG(p.semver) OVER (
                PARTITION BY h.tool_name, p.plugin_name ORDER BY p.recorded_at
            ) AS prev_semver,
            CASE
                WHEN LAG(p.semver) OVER (
                    PARTITION BY h.tool_name, p.plugin_name ORDER BY p.recorded_at
                ) IS NOT NULL
                 AND LAG(p.semver) OVER (
                    PARTITION BY h.tool_name, p.plugin_name ORDER BY p.recorded_at
                ) <> p.semver
                THEN 1 ELSE 0
            END AS version_changed
        FROM agentic_plugins p
        JOIN agentic_harnesses h ON h.session_id = p.session_id
        ORDER BY p.plugin_name, p.recorded_at
    """,
    "agentic_skill_outcomes": """
        SELECT
            sub.skill_name,
            sub.outcome,
            sub.rfc_version,
            sub.sha_changed,
            COUNT(*) AS session_count
        FROM (
            SELECT
                COALESCE(s.skill_name, s.skill_path) AS skill_name,
                COALESCE(h.outcome, 'unknown') AS outcome,
                h.rfc_version,
                CASE
                    WHEN LAG(s.git_sha) OVER (
                        PARTITION BY s.skill_path ORDER BY s.recorded_at
                    ) IS NOT NULL
                     AND LAG(s.git_sha) OVER (
                        PARTITION BY s.skill_path ORDER BY s.recorded_at
                    ) <> s.git_sha
                    THEN 1 ELSE 0
                END AS sha_changed
            FROM agentic_skills s
            JOIN agentic_harnesses h ON h.session_id = s.session_id
        ) sub
        GROUP BY sub.skill_name, sub.outcome, sub.rfc_version, sub.sha_changed
    """,
    "agentic_outcome_funnel": """
        SELECT
            tool_name,
            rfc_version,
            COALESCE(outcome, 'running') AS outcome,
            COUNT(*) AS session_count
        FROM agentic_harnesses
        GROUP BY tool_name, rfc_version, COALESCE(outcome, 'running')
    """,
}

_AGENTIC_CHART_DEFS: list[dict[str, Any]] = [
    {
        "slice_name": "Harness Comparison",
        "viz_type": "table",
        "datasource_id_key": "agentic_sessions_full",
        "params": {
            "columns": [
                "started_ts",
                "tool_name",
                "tool_version",
                "model_id",
                "rfc_version",
                "branch",
                "outcome",
                "tokens_in",
                "tokens_out",
                "avg_latency_ms",
                "avg_grader_score",
            ],
            "order_desc": True,
            "row_limit": 100,
        },
    },
    {
        "slice_name": "Plugin Drift",
        "viz_type": "table",
        "datasource_id_key": "agentic_plugin_drift",
        "params": {
            "columns": [
                "recorded_at",
                "tool_name",
                "plugin_name",
                "semver",
                "prev_semver",
                "version_changed",
            ],
            "order_desc": True,
            "row_limit": 200,
            "conditional_formatting": [
                {
                    "column": "version_changed",
                    "operator": ">",
                    "targetValue": 0,
                    "colorScheme": STATUS_COLORS["FAIL"],
                },
            ],
        },
    },
    {
        "slice_name": "Skill SHA Heatmap",
        "viz_type": "heatmap_v2",
        "datasource_id_key": "agentic_skill_outcomes",
        "params": {
            "x_axis": "skill_name",
            "groupby": "outcome",
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "session_count"},
                "aggregate": "SUM",
                "label": "Sessions",
            },
            "legend_type": "continuous",
            "normalize_across": "heatmap",
        },
    },
    {
        "slice_name": "Token Burn Rate",
        "viz_type": "echarts_timeseries_bar",
        "datasource_id_key": "agentic_sessions_full",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "tokens_in"},
                    "aggregate": "SUM",
                    "label": "Tokens In",
                },
                {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": "tokens_out"},
                    "aggregate": "SUM",
                    "label": "Tokens Out",
                },
            ],
            "groupby": ["tool_name"],
            "x_axis": "started_ts",
            "granularity_sqla": "started_ts",
        },
    },
    {
        "slice_name": "Outcome Funnel",
        "viz_type": "funnel",
        "datasource_id_key": "agentic_outcome_funnel",
        "params": {
            "groupby": ["tool_name", "outcome"],
            "metric": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "session_count"},
                "aggregate": "SUM",
                "label": "Sessions",
            },
            "row_limit": 50,
        },
    },
    {
        "slice_name": "Latency vs Grader Score",
        "viz_type": "bubble_v2",
        "datasource_id_key": "agentic_sessions_full",
        "params": {
            "entity": "session_id",
            "series": "tool_name",
            "x": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "avg_latency_ms"},
                "aggregate": "AVG",
                "label": "Latency (ms)",
            },
            "y": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "avg_grader_score"},
                "aggregate": "AVG",
                "label": "Grader Score",
            },
            "size": {
                "expressionType": "SIMPLE",
                "column": {"column_name": "tokens_out"},
                "aggregate": "SUM",
                "label": "Tokens Out",
            },
            "row_limit": 500,
        },
    },
]

_AGENTIC_FILTER_CONFIGS: list[dict[str, Any]] = [
    {
        "id": "AGENTIC_FILTER-TOOL",
        "name": "Tool",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "tool_name"},
                "datasetId": "__AGENTIC_SESSIONS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "AGENTIC_FILTER-MODEL",
        "name": "Model",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "model_id"},
                "datasetId": "__AGENTIC_SESSIONS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "AGENTIC_FILTER-VERSION",
        "name": "RFC Version",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "rfc_version"},
                "datasetId": "__AGENTIC_SESSIONS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
    {
        "id": "AGENTIC_FILTER-OUTCOME",
        "name": "Outcome",
        "filterType": "filter_select",
        "targets": [
            {
                "column": {"name": "outcome"},
                "datasetId": "__AGENTIC_SESSIONS_ID__",
            },
        ],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
    },
]

_AGENTIC_LAYOUT_SECTIONS: list[dict[str, Any]] = [
    {
        "label": "Harness Comparison",
        "charts": [
            {"name": "Harness Comparison", "width": 12, "height": 50},
        ],
    },
    {
        "label": "Outcomes",
        "charts": [
            {"name": "Outcome Funnel", "width": 6, "height": 50},
            {"name": "Latency vs Grader Score", "width": 6, "height": 50},
        ],
    },
    {
        "label": "Token Burn",
        "charts": [
            {"name": "Token Burn Rate", "width": 12, "height": 50},
        ],
    },
    {
        "label": "Stack Drift",
        "charts": [
            {"name": "Plugin Drift", "width": 6, "height": 50},
            {"name": "Skill SHA Heatmap", "width": 6, "height": 50},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agentic_dataset_is_current(
    stored_sql: str | None,
    stored_columns: "list[str]",
    target_sql: str,
    *,
    required_column: str = "rfc_version",
) -> bool:
    """Whether an existing agentic virtual dataset needs no refresh.

    A SQL match alone does not prove the dataset is current: ``fetch_metadata``
    can fail independently of the SQL commit (it raises on empty virtual
    datasets), so the stored columns can lag the SQL — leaving ``rfc_version``
    absent and the native filter broken. The dataset is current only when its
    SQL matches AND its stored columns include ``required_column``; otherwise
    the next bootstrap must retry the metadata refresh (#508).
    """
    if (stored_sql or "").strip() != target_sql.strip():
        return False
    return required_column in set(stored_columns)


def _probe_columns(database_uri: str, sql: str) -> list[str]:
    """Discover column names by running ``sql`` with LIMIT 0.

    When Superset's ``fetch_metadata()`` fails on virtual datasets with
    empty underlying tables, this function discovers column names by
    executing the SQL with LIMIT 0 — the database infers types from
    the query plan without scanning any rows.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(database_uri)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT * FROM ({sql}) sq LIMIT 0"))
            return list(result.keys())
    finally:
        engine.dispose()


def _build_position_json(chart_id_map: dict[str, int]) -> dict[str, Any]:
    """Build Superset dashboard ``position_json`` from _LAYOUT_SECTIONS.

    Args:
        chart_id_map: mapping of chart slice_name -> Superset slice ID.

    Returns:
        Dict suitable for ``Dashboard.position_json``.
    """
    layout: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
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
            "meta": {"text": "RFC Test Health"},
        },
    }

    row_counter = 0
    for section in _LAYOUT_SECTIONS:
        row_id = f"ROW-{row_counter}"
        row: dict[str, Any] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        layout["GRID_ID"]["children"].append(row_id)

        for chart_spec in section["charts"]:
            chart_name = chart_spec["name"]
            chart_db_id = chart_id_map.get(chart_name, 0)
            chart_key = f"CHART-{chart_db_id}"
            row["children"].append(chart_key)
            layout[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "meta": {
                    "chartId": chart_db_id,
                    "width": chart_spec["width"],
                    "height": chart_spec["height"],
                    "sliceName": chart_name,
                },
            }

        layout[row_id] = row
        row_counter += 1

    return layout


def _build_json_metadata(
    test_runs_dataset_id: int,
) -> dict[str, Any]:
    """Build dashboard ``json_metadata`` with native filters.

    Substitutes the placeholder dataset IDs in _FILTER_CONFIGS with the
    actual ``test_runs`` dataset ID at runtime.
    """
    filters = []
    for fconf in _FILTER_CONFIGS:
        f = json.loads(json.dumps(fconf))  # deep copy
        # Replace placeholder dataset IDs
        for target in f.get("targets", []):
            if target.get("datasetId") == "__TEST_RUNS_ID__":
                target["datasetId"] = test_runs_dataset_id
        filters.append(f)

    return {
        "native_filter_configuration": filters,
        "chart_configuration": {},
        "cross_filters_enabled": True,
    }


def _build_infra_position_json(chart_id_map: dict[str, int]) -> dict[str, Any]:
    """Build Superset dashboard ``position_json`` for Test Infrastructure.

    Args:
        chart_id_map: mapping of chart slice_name -> Superset slice ID.

    Returns:
        Dict suitable for ``Dashboard.position_json``.
    """
    layout: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
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
            "meta": {"text": "Test Infrastructure"},
        },
    }

    row_counter = 0
    for section in _INFRA_LAYOUT_SECTIONS:
        row_id = f"ROW-{row_counter}"
        row: dict[str, Any] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        layout["GRID_ID"]["children"].append(row_id)

        for chart_spec in section["charts"]:
            chart_name = chart_spec["name"]
            chart_db_id = chart_id_map.get(chart_name, 0)
            chart_key = f"CHART-{chart_db_id}"
            row["children"].append(chart_key)
            layout[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "meta": {
                    "chartId": chart_db_id,
                    "width": chart_spec["width"],
                    "height": chart_spec["height"],
                    "sliceName": chart_name,
                },
            }

        layout[row_id] = row
        row_counter += 1

    return layout


def _build_infra_json_metadata(
    test_runs_dataset_id: int,
    coverage_dataset_id: int,
) -> dict[str, Any]:
    """Build dashboard ``json_metadata`` for Test Infrastructure.

    Substitutes placeholder dataset IDs in _INFRA_FILTER_CONFIGS.
    """
    filters = []
    for fconf in _INFRA_FILTER_CONFIGS:
        f = json.loads(json.dumps(fconf))  # deep copy
        for target in f.get("targets", []):
            if target.get("datasetId") == "__TEST_RUNS_ID__":
                target["datasetId"] = test_runs_dataset_id
            elif target.get("datasetId") == "__COVERAGE_ID__":
                target["datasetId"] = coverage_dataset_id
        filters.append(f)

    return {
        "native_filter_configuration": filters,
        "chart_configuration": {},
        "cross_filters_enabled": True,
    }


def _build_sectioned_position_json(
    sections: list[dict[str, Any]],
    header_text: str,
    chart_id_map: dict[str, int],
) -> dict[str, Any]:
    """Build Superset dashboard ``position_json`` from layout sections.

    Generic equivalent of _build_position_json/_build_infra_position_json.

    Args:
        sections: layout sections (label + chart name/width/height specs).
        header_text: dashboard header title.
        chart_id_map: mapping of chart slice_name -> Superset slice ID.

    Returns:
        Dict suitable for ``Dashboard.position_json``.
    """
    layout: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
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
            "meta": {"text": header_text},
        },
    }

    row_counter = 0
    for section in sections:
        row_id = f"ROW-{row_counter}"
        row: dict[str, Any] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        layout["GRID_ID"]["children"].append(row_id)

        for chart_spec in section["charts"]:
            chart_name = chart_spec["name"]
            chart_db_id = chart_id_map.get(chart_name, 0)
            chart_key = f"CHART-{chart_db_id}"
            row["children"].append(chart_key)
            layout[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "meta": {
                    "chartId": chart_db_id,
                    "width": chart_spec["width"],
                    "height": chart_spec["height"],
                    "sliceName": chart_name,
                },
            }

        layout[row_id] = row
        row_counter += 1

    return layout


def _build_agentic_position_json(chart_id_map: dict[str, int]) -> dict[str, Any]:
    """Build dashboard ``position_json`` for the Agentic Stack Tracker."""
    return _build_sectioned_position_json(
        _AGENTIC_LAYOUT_SECTIONS, "Agentic Stack Tracker", chart_id_map
    )


def _build_agentic_json_metadata(sessions_dataset_id: int) -> dict[str, Any]:
    """Build dashboard ``json_metadata`` for the Agentic Stack Tracker.

    Substitutes the ``__AGENTIC_SESSIONS_ID__`` placeholder in
    _AGENTIC_FILTER_CONFIGS with the ``agentic_sessions_full`` dataset ID.
    """
    filters = []
    for fconf in _AGENTIC_FILTER_CONFIGS:
        f = json.loads(json.dumps(fconf))  # deep copy
        for target in f.get("targets", []):
            if target.get("datasetId") == "__AGENTIC_SESSIONS_ID__":
                target["datasetId"] = sessions_dataset_id
        filters.append(f)

    return {
        "native_filter_configuration": filters,
        "chart_configuration": {},
        "cross_filters_enabled": True,
    }


# ---------------------------------------------------------------------------
# Bootstrap functions
# ---------------------------------------------------------------------------


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
        _create_charts_and_dashboard(db_id)
        _create_infra_dashboard(db_id)
        _create_agentic_datasets(db_id)
        _create_agentic_dashboard(db_id)

    log.info("Bootstrap complete.")


def _run_ddl(ddl: str) -> None:
    """Execute a semicolon-separated DDL block against the RFC database."""
    from sqlalchemy import create_engine, text

    uri = _get_database_uri()
    engine = create_engine(uri)
    with engine.begin() as conn:
        for statement in ddl.split(";"):
            # Strip SQL comment lines so comment-only fragments are skipped.
            executable = "\n".join(
                ln
                for ln in statement.splitlines()
                if ln.strip() and not ln.strip().startswith("--")
            ).strip()
            if executable:
                conn.execute(text(statement.strip()))
    engine.dispose()


def _create_tables() -> None:
    """Create the test-result and agentic-stack schemas in PostgreSQL."""
    _run_ddl(_TABLE_DDL)
    log.info("Created 2-table schema (test_runs, test_results).")
    _run_ddl(_AGENTIC_TABLE_DDL)
    log.info(
        "Created agentic stack schema "
        "(agentic_* tables, dialog_*, agentic_sessions_full view)."
    )


def _ensure_database_connection() -> int | None:
    """Create or update the Superset database connection object."""
    from superset import db as superset_db  # type: ignore[attr-defined]
    from superset.models.core import Database

    db_name = "Robot Framework Results"
    uri = _get_database_uri()

    existing = (
        superset_db.session.query(Database).filter_by(database_name=db_name).first()
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
    """Create Superset datasets for tables, views, and virtual datasets."""
    from superset import db as superset_db  # type: ignore[attr-defined]
    from superset.connectors.sqla.models import SqlaTable

    # Physical tables and views
    for table_name in [
        "test_runs",
        "test_results",
        "test_results_full",
        "coverage_reports",
    ]:
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

        try:
            dataset.fetch_metadata()
            superset_db.session.commit()
        except Exception as e:
            log.warning(f"fetch_metadata failed for {table_name}: {e}")

        log.info(f"Created dataset: {table_name} (id={dataset.id})")

    # Virtual datasets (SQL-based)
    uri = _get_database_uri()
    for vds_name, vds_sql in _VIRTUAL_DATASETS.items():
        existing = (
            superset_db.session.query(SqlaTable)
            .filter_by(table_name=vds_name, database_id=db_id)
            .first()
        )
        if existing:
            log.info(f"Virtual dataset already exists: {vds_name}")
            continue

        dataset = SqlaTable(
            table_name=vds_name,
            database_id=db_id,
            schema=None,
            sql=vds_sql,
        )
        superset_db.session.add(dataset)
        superset_db.session.commit()

        try:
            dataset.fetch_metadata()
            superset_db.session.commit()
        except Exception:
            log.warning(
                f"fetch_metadata failed for {vds_name}, "
                "trying _probe_columns fallback: {e}"
            )
            try:
                cols = _probe_columns(uri, vds_sql)
                log.info(f"Probed {len(cols)} columns for {vds_name}: {cols}")
            except Exception as probe_err:
                log.warning(f"_probe_columns also failed for {vds_name}: {probe_err}")

        log.info(f"Created virtual dataset: {vds_name} (id={dataset.id})")


def _create_charts_and_dashboard(db_id: int) -> None:
    """Create charts and the consolidated RFC Test Health dashboard."""
    from superset import db as superset_db  # type: ignore[attr-defined]
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    # Build dataset name -> ID map (includes physical + virtual datasets)
    datasets: dict[str, int] = {}
    all_dataset_names = [
        "test_runs",
        "test_results",
        "test_results_full",
    ] + list(_VIRTUAL_DATASETS.keys())

    for table_name in all_dataset_names:
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

    # Create charts from _CHART_DEFS
    chart_id_map: dict[str, int] = {}
    for chart_def in _CHART_DEFS:
        ds_key = chart_def["datasource_id_key"]
        if ds_key not in datasets:
            log.warning(
                f"Skipping chart '{chart_def['slice_name']}': "
                f"dataset '{ds_key}' not found."
            )
            continue

        ds_id = datasets[ds_key]
        slice_name = chart_def["slice_name"]

        existing = (
            superset_db.session.query(Slice).filter_by(slice_name=slice_name).first()
        )
        if existing:
            chart_id_map[slice_name] = existing.id
            log.info(f"Chart already exists: {slice_name}")
            continue

        chart = Slice(
            slice_name=slice_name,
            viz_type=chart_def["viz_type"],
            datasource_id=ds_id,
            datasource_type="table",
            params=json.dumps(chart_def["params"]),
        )
        superset_db.session.add(chart)
        superset_db.session.commit()
        chart_id_map[slice_name] = chart.id
        log.info(f"Created chart: {slice_name} (id={chart.id})")

    # Build layout and metadata
    position = _build_position_json(chart_id_map)
    test_runs_ds_id = datasets.get("test_runs", 0)
    metadata = _build_json_metadata(test_runs_ds_id)

    # Create consolidated dashboard
    slug = "rfc-test-health"
    existing_dash = superset_db.session.query(Dashboard).filter_by(slug=slug).first()
    if existing_dash:
        # Update layout and metadata on existing dashboard
        existing_dash.position_json = json.dumps(position)
        existing_dash.json_metadata = json.dumps(metadata)
        existing_dash.slices = [
            superset_db.session.query(Slice).get(cid)
            for cid in chart_id_map.values()
            if superset_db.session.query(Slice).get(cid)
        ]
        superset_db.session.commit()
        log.info(f"Updated dashboard: RFC Test Health (id={existing_dash.id})")
        return

    dashboard = Dashboard(
        dashboard_title="RFC Test Health",
        slug=slug,
        published=True,
        position_json=json.dumps(position),
        json_metadata=json.dumps(metadata),
    )
    dashboard.slices = [
        superset_db.session.query(Slice).get(cid)
        for cid in chart_id_map.values()
        if superset_db.session.query(Slice).get(cid)
    ]
    superset_db.session.add(dashboard)
    superset_db.session.commit()
    log.info(f"Created dashboard: RFC Test Health (id={dashboard.id})")


def _create_infra_dashboard(db_id: int) -> None:
    """Create charts and the Test Infrastructure dashboard."""
    from superset import db as superset_db  # type: ignore[attr-defined]
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    # Build dataset name -> ID map
    datasets: dict[str, int] = {}
    all_dataset_names = [
        "test_runs",
        "test_results",
        "test_results_full",
        "coverage_reports",
    ] + list(_VIRTUAL_DATASETS.keys())

    for table_name in all_dataset_names:
        ds = (
            superset_db.session.query(SqlaTable)
            .filter_by(table_name=table_name, database_id=db_id)
            .first()
        )
        if ds:
            datasets[table_name] = ds.id

    if not datasets:
        log.warning("No datasets found; skipping infra dashboard creation.")
        return

    # Create charts from _INFRA_CHART_DEFS
    chart_id_map: dict[str, int] = {}
    for chart_def in _INFRA_CHART_DEFS:
        ds_key = chart_def["datasource_id_key"]
        if ds_key not in datasets:
            log.warning(
                f"Skipping infra chart '{chart_def['slice_name']}': "
                f"dataset '{ds_key}' not found."
            )
            continue

        ds_id = datasets[ds_key]
        slice_name = chart_def["slice_name"]

        existing = (
            superset_db.session.query(Slice).filter_by(slice_name=slice_name).first()
        )
        if existing:
            chart_id_map[slice_name] = existing.id
            log.info(f"Infra chart already exists: {slice_name}")
            continue

        chart = Slice(
            slice_name=slice_name,
            viz_type=chart_def["viz_type"],
            datasource_id=ds_id,
            datasource_type="table",
            params=json.dumps(chart_def["params"]),
        )
        superset_db.session.add(chart)
        superset_db.session.commit()
        chart_id_map[slice_name] = chart.id
        log.info(f"Created infra chart: {slice_name} (id={chart.id})")

    # Build layout and metadata
    position = _build_infra_position_json(chart_id_map)
    test_runs_ds_id = datasets.get("test_runs", 0)
    coverage_ds_id = datasets.get("coverage_reports", 0)
    metadata = _build_infra_json_metadata(test_runs_ds_id, coverage_ds_id)

    # Create infrastructure dashboard
    slug = "test-infrastructure"
    existing_dash = superset_db.session.query(Dashboard).filter_by(slug=slug).first()
    if existing_dash:
        existing_dash.position_json = json.dumps(position)
        existing_dash.json_metadata = json.dumps(metadata)
        existing_dash.slices = [
            superset_db.session.query(Slice).get(cid)
            for cid in chart_id_map.values()
            if superset_db.session.query(Slice).get(cid)
        ]
        superset_db.session.commit()
        log.info(f"Updated dashboard: Test Infrastructure (id={existing_dash.id})")
        return

    dashboard = Dashboard(
        dashboard_title="Test Infrastructure",
        slug=slug,
        published=True,
        position_json=json.dumps(position),
        json_metadata=json.dumps(metadata),
    )
    dashboard.slices = [
        superset_db.session.query(Slice).get(cid)
        for cid in chart_id_map.values()
        if superset_db.session.query(Slice).get(cid)
    ]
    superset_db.session.add(dashboard)
    superset_db.session.commit()
    log.info(f"Created dashboard: Test Infrastructure (id={dashboard.id})")


def _create_agentic_datasets(db_id: int) -> None:
    """Create Superset datasets for the Agentic Stack Tracker."""
    from superset import db as superset_db  # type: ignore[attr-defined]
    from superset.connectors.sqla.models import SqlaTable

    # Physical tables and the agentic_sessions_full view
    for table_name in _AGENTIC_DATASET_TABLES:
        existing = (
            superset_db.session.query(SqlaTable)
            .filter_by(table_name=table_name, database_id=db_id)
            .first()
        )
        if existing:
            log.info(f"Agentic dataset already exists: {table_name}")
            continue

        dataset = SqlaTable(
            table_name=table_name,
            database_id=db_id,
            schema=None,
        )
        superset_db.session.add(dataset)
        superset_db.session.commit()

        try:
            dataset.fetch_metadata()
            superset_db.session.commit()
        except Exception as e:
            log.warning(f"fetch_metadata failed for {table_name}: {e}")

        log.info(f"Created agentic dataset: {table_name} (id={dataset.id})")

    # Virtual datasets (SQL-based)
    uri = _get_database_uri()
    for vds_name, vds_sql in _AGENTIC_VIRTUAL_DATASETS.items():
        existing = (
            superset_db.session.query(SqlaTable)
            .filter_by(table_name=vds_name, database_id=db_id)
            .first()
        )
        if existing:
            stored_cols = [c.column_name for c in (existing.columns or [])]
            if _agentic_dataset_is_current(existing.sql, stored_cols, vds_sql):
                log.info(f"Agentic virtual dataset up to date: {vds_name}")
                continue
            # Either the SQL changed in code (e.g. new rfc_version column,
            # #483) or a previous fetch_metadata failed and left the columns
            # without rfc_version (#508). Commit any SQL change, then retry the
            # metadata refresh — committing the SQL alone would mark the
            # dataset "current" on the next run and never repopulate columns.
            if (existing.sql or "").strip() != vds_sql.strip():
                existing.sql = vds_sql
                superset_db.session.commit()
            try:
                existing.fetch_metadata()
                superset_db.session.commit()
            except Exception as e:
                log.warning(
                    f"fetch_metadata failed for {vds_name} (will retry on next "
                    f"bootstrap until rfc_version columns populate): {e}"
                )
            log.info(f"Refreshed agentic virtual dataset: {vds_name}")
            continue

        dataset = SqlaTable(
            table_name=vds_name,
            database_id=db_id,
            schema=None,
            sql=vds_sql,
        )
        superset_db.session.add(dataset)
        superset_db.session.commit()

        try:
            dataset.fetch_metadata()
            superset_db.session.commit()
        except Exception as e:
            log.warning(
                f"fetch_metadata failed for {vds_name}, "
                f"trying _probe_columns fallback: {e}"
            )
            try:
                cols = _probe_columns(uri, vds_sql)
                log.info(f"Probed {len(cols)} columns for {vds_name}: {cols}")
            except Exception as probe_err:
                log.warning(f"_probe_columns also failed for {vds_name}: {probe_err}")

        log.info(f"Created agentic virtual dataset: {vds_name} (id={dataset.id})")


def _create_agentic_dashboard(db_id: int) -> None:
    """Create charts and the Agentic Stack Tracker dashboard."""
    from superset import db as superset_db  # type: ignore[attr-defined]
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    # Build dataset name -> ID map
    datasets: dict[str, int] = {}
    all_dataset_names = _AGENTIC_DATASET_TABLES + list(_AGENTIC_VIRTUAL_DATASETS)

    for table_name in all_dataset_names:
        ds = (
            superset_db.session.query(SqlaTable)
            .filter_by(table_name=table_name, database_id=db_id)
            .first()
        )
        if ds:
            datasets[table_name] = ds.id

    if not datasets:
        log.warning("No agentic datasets found; skipping agentic dashboard.")
        return

    # Create charts from _AGENTIC_CHART_DEFS
    chart_id_map: dict[str, int] = {}
    for chart_def in _AGENTIC_CHART_DEFS:
        ds_key = chart_def["datasource_id_key"]
        if ds_key not in datasets:
            log.warning(
                f"Skipping agentic chart '{chart_def['slice_name']}': "
                f"dataset '{ds_key}' not found."
            )
            continue

        ds_id = datasets[ds_key]
        slice_name = chart_def["slice_name"]

        existing = (
            superset_db.session.query(Slice).filter_by(slice_name=slice_name).first()
        )
        if existing:
            chart_id_map[slice_name] = existing.id
            log.info(f"Agentic chart already exists: {slice_name}")
            continue

        chart = Slice(
            slice_name=slice_name,
            viz_type=chart_def["viz_type"],
            datasource_id=ds_id,
            datasource_type="table",
            params=json.dumps(chart_def["params"]),
        )
        superset_db.session.add(chart)
        superset_db.session.commit()
        chart_id_map[slice_name] = chart.id
        log.info(f"Created agentic chart: {slice_name} (id={chart.id})")

    # Build layout and metadata
    position = _build_agentic_position_json(chart_id_map)
    sessions_ds_id = datasets.get("agentic_sessions_full", 0)
    metadata = _build_agentic_json_metadata(sessions_ds_id)

    # Create the Agentic Stack Tracker dashboard
    slug = "agentic-stack-tracker"
    existing_dash = superset_db.session.query(Dashboard).filter_by(slug=slug).first()
    if existing_dash:
        existing_dash.position_json = json.dumps(position)
        existing_dash.json_metadata = json.dumps(metadata)
        existing_dash.slices = [
            superset_db.session.query(Slice).get(cid)
            for cid in chart_id_map.values()
            if superset_db.session.query(Slice).get(cid)
        ]
        superset_db.session.commit()
        log.info(f"Updated dashboard: Agentic Stack Tracker (id={existing_dash.id})")
        return

    dashboard = Dashboard(
        dashboard_title="Agentic Stack Tracker",
        slug=slug,
        published=True,
        position_json=json.dumps(position),
        json_metadata=json.dumps(metadata),
    )
    dashboard.slices = [
        superset_db.session.query(Slice).get(cid)
        for cid in chart_id_map.values()
        if superset_db.session.query(Slice).get(cid)
    ]
    superset_db.session.add(dashboard)
    superset_db.session.commit()
    log.info(f"Created dashboard: Agentic Stack Tracker (id={dashboard.id})")


if __name__ == "__main__":
    bootstrap()
