# Grafana & Superset Setup Guide

Complete guide for setting up the visualization stack, populating the database,
and using dashboards to compare LLM model performance.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Step-by-Step Setup](#step-by-step-setup)
   - [Environment Configuration](#environment-configuration)
   - [Starting the Stack](#starting-the-stack)
   - [Bootstrapping Superset](#bootstrapping-superset)
   - [Verifying Services](#verifying-services)
5. [Populating the Database](#populating-the-database)
   - [Running Tests with Archiving](#running-tests-with-archiving)
   - [Importing Existing Results](#importing-existing-results)
6. [Grafana Dashboards](#grafana-dashboards)
   - [Accessing Grafana](#accessing-grafana)
   - [Pre-provisioned Dashboards](#pre-provisioned-dashboards)
   - [Template Variables](#template-variables)
   - [Creating Custom Panels](#creating-custom-panels)
7. [Superset Dashboards](#superset-dashboards)
   - [Accessing Superset](#accessing-superset)
   - [Pre-configured Dashboards](#pre-configured-dashboards)
   - [Using SQL Lab](#using-sql-lab)
8. [Model Comparison Reports](#model-comparison-reports)
   - [CLI Comparison Tools](#cli-comparison-tools)
   - [Grafana: Visual Model Comparison](#grafana-visual-model-comparison)
   - [Superset: Cross-Model Analytics](#superset-cross-model-analytics)
   - [SQL Queries for Model Comparison](#sql-queries-for-model-comparison)
   - [Programmatic Comparison](#programmatic-comparison)
9. [Database Schema Reference](#database-schema-reference)
10. [Troubleshooting](#troubleshooting)
11. [Maintenance](#maintenance)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Stack                          │
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐  │
│  │   Grafana    │   │   Superset   │   │   Superset-Init          │  │
│  │  :3000       │   │   :8088      │   │   (one-shot bootstrap)   │  │
│  │  Dashboards  │   │   Dashboards │   │   Creates tables,        │  │
│  │  provisione  │   │   SQL Lab    │   │   charts, dashboards     │  │
│  └──────┬───────┘   └──────┬───────┘   └────────────┬─────────────┘  │
│         │                  │                        │                │
│         └────────────┬─────┴────────────────────────┘                │
│                      │                                               │
│              ┌───────▼───────┐         ┌──────────────┐              │
│              │  PostgreSQL   │         │    Redis     │              │
│              │  :5432 (int)  │◄────────│    (cache)   │              │
│              │  :5433 (ext)  │         └──────────────┘              │
│              └───────────────┘                                       │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                       ▲
                       │ DATABASE_URL
                       │
┌──────────────────────┴───────────────────────────────────────────────┐
│  Robot Framework Tests                                               │
│                                                                      │
│  make robot-math ──► DbListener ──► PostgreSQL                       │
│                      GitMetaData                                     │
│                      OllamaTimestampListener                         │
│                                                                      │
│  scripts/query_results.py ──► CLI model comparison                   │
│  scripts/import_test_results.py ──► Bulk import output.xml           │
└──────────────────────────────────────────────────────────────────────┘
```

**Components:**

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| PostgreSQL | `postgres:16-alpine` | 5433 (host) / 5432 (internal) | Primary data store for test results |
| Redis | `redis:7-alpine` | — (internal only) | Superset caching backend |
| Superset | `apache/superset:4.1.1` | 8088 | Interactive dashboards and SQL Lab |
| Grafana | `grafana/grafana-oss:11.4.0` | 3000 | Provisioned dashboards |

---

## Prerequisites

- **Docker** with Docker Compose V2 (`docker compose` — not `docker-compose`)
- **Python 3.11+** with `uv` package manager
- **Git** (for version tracking in test results)
- **Ollama** running locally or on a network node (for actual LLM testing)

Verify Docker Compose V2:

```bash
docker compose version
# Docker Compose version v2.x.x
```

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd robotframework-chat

# 2. Install Python dependencies
make install

# 3. Configure environment
cp .env.example .env
# Edit .env — at minimum change POSTGRES_PASSWORD and SUPERSET_SECRET_KEY

# 4. Start the full stack
make docker-up

# 5. Bootstrap Superset (first time only — creates tables, charts, dashboards)
make bootstrap

# 6. Run tests to populate data
make robot-math

# 7. Open dashboards
open http://localhost:3000    # Grafana (admin/admin)
open http://localhost:8088    # Superset (admin/changeme)
```

---

## Step-by-Step Setup

### Environment Configuration

Copy the example environment file and customize it:

```bash
cp .env.example .env
```

Edit `.env` with your preferred credentials:

```bash
# ── PostgreSQL ──────────────────────────────────────────────────────
POSTGRES_USER=rfc
POSTGRES_PASSWORD=changeme          # CHANGE THIS in production
POSTGRES_DB=rfc
POSTGRES_PORT=5433                  # Host port (5432 is internal)

# ── Superset ────────────────────────────────────────────────────────
SUPERSET_SECRET_KEY=generate-a-random-secret-here   # CHANGE THIS
SUPERSET_PORT=8088
SUPERSET_ADMIN_USER=admin
SUPERSET_ADMIN_PASSWORD=changeme    # CHANGE THIS
SUPERSET_ADMIN_EMAIL=admin@rfc.local

# ── Grafana ─────────────────────────────────────────────────────────
GRAFANA_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin        # CHANGE THIS

# ── Test runner ─────────────────────────────────────────────────────
# This tells the DbListener to archive results to PostgreSQL
DATABASE_URL=postgresql://rfc:changeme@localhost:5433/rfc

# ── Ollama ──────────────────────────────────────────────────────────
OLLAMA_ENDPOINT=http://localhost:11434
DEFAULT_MODEL=phi4:14b
OLLAMA_NODES_LIST=localhost
```

**Important:** The `DATABASE_URL` must match the PostgreSQL credentials above.
When `DATABASE_URL` is unset, the test harness falls back to local SQLite
(`data/test_history.db`).

### Starting the Stack

```bash
# Start all services in the background
make docker-up

# Watch startup logs
make docker-logs
```

This starts PostgreSQL, Redis, Superset (init + web), and Grafana. Wait for
all health checks to pass (visible in `docker compose ps`):

```bash
docker compose ps
```

Expected output:

```
NAME                STATUS              PORTS
postgres            Up (healthy)        0.0.0.0:5433->5432/tcp
redis               Up (healthy)
superset-init       Exited (0)
superset            Up (healthy)        0.0.0.0:8088->8088/tcp
grafana             Up (healthy)        0.0.0.0:3000->3000/tcp
```

### Bootstrapping Superset

The first time you start the stack, Superset needs initialization:

```bash
make bootstrap
```

This one-shot command:
1. Runs Superset database migrations
2. Creates the admin user (credentials from `.env`)
3. Initializes Superset internals
4. Executes `superset/bootstrap_dashboards.py` which:
   - Creates the PostgreSQL tables: `test_runs`, `test_results`,
     `test_run_artifacts`, `test_result_artifacts`, and `coverage_reports`
   - Creates the `test_results_full` view (LEFT-JOINs the artifact
     tables so drill-down still sees question/answer/grading text)
   - Creates indexes for query performance
   - Registers the PostgreSQL connection in Superset as
     "Robot Framework Results"
   - Creates virtual datasets and charts across the RFC Test Health
     dashboard

**You only need to run `make bootstrap` once.** Subsequent `make docker-up`
commands will reuse the existing data.

### Verifying Services

After startup, verify each service:

```bash
# PostgreSQL — check tables exist
psql $DATABASE_URL -c "\dt"

# Grafana health
curl -s http://localhost:3000/api/health | python3 -m json.tool

# Superset health
curl -s http://localhost:8088/health
```

---

## Populating the Database

Dashboards need data. There are two ways to populate the database.

### Running Tests with Archiving

Every `make robot-*` target automatically attaches three listeners that archive
results in real-time:

```bash
# Run math test suite (results archived to PostgreSQL automatically)
make robot-math

# Run all suites
make robot

# Run tests then import combined results
make robot-import
```

The `DbListener` captures:
- **`start_suite`** — records start time, collects CI metadata (git branch,
  commit, pipeline URL)
- **`end_test`** — accumulates per-test results (name, status, score, question,
  expected/actual answers, grading reason)
- **`end_suite`** — writes a `test_run` row and all `test_result` rows to the
  database

### Importing Existing Results

If you have `output.xml` files from previous test runs:

```bash
# Import a single output.xml
uv run python scripts/import_test_results.py results/math/output.xml

# Import all output.xml files recursively from a directory
uv run python scripts/import_test_results.py results/ --recursive

# Import with a specific model name
uv run python scripts/import_test_results.py results/math/output.xml --model llama3.1

# Using the Makefile shortcut
make import RESULTS_DIR=results/
```

---

## Grafana Dashboards

### Accessing Grafana

Open `http://localhost:3000` and log in with the credentials from `.env`
(default: `admin` / `admin`).

The PostgreSQL datasource is auto-provisioned via
`grafana/provisioning/datasources/rfc.yaml`. No manual datasource configuration
is needed.

### Pre-provisioned Dashboards

Three JSON dashboards are provisioned automatically in the "Robot Framework Chat"
folder:

#### 1. RFC Test Results (`rfc_test_results.json`)

The primary dashboard for monitoring test execution and model quality.

**Summary Row (6 stat panels):**

| Panel | Description |
|-------|-------------|
| Total Test Runs | Count of all test suite executions |
| Total Tests Executed | Sum of all individual tests run |
| Overall Pass Rate | Aggregate pass rate with color thresholds (red < 70%, yellow < 90%, green >= 90%) |
| Total Failures | Failure count with severity thresholds |
| Models Tested | Count of distinct models evaluated |
| Avg Duration | Average suite execution time |

**Charts:**

| Panel | Type | Description |
|-------|------|-------------|
| Pass / Fail Over Time | Stacked bar (time series) | Green/red/yellow bars for passed/failed/skipped tests over time |
| Suite Duration Over Time | Line (time series) | Execution time trends per suite |
| Pass Rate by Model | Bar chart | Side-by-side model comparison — the key comparison chart |
| Pass Rate by Suite | Bar chart | Performance breakdown by test suite |
| Recent Test Runs | Table | Latest 25 runs with model, suite, pass/fail counts, branch, commit |
| Individual Test Results | Table | Per-test details from the most recent run (status, score, actual vs expected answer) |
| Score Distribution Over Time | Line (time series) | Average score trend over time |
| Test Status Distribution | Pie chart | Overall pass/fail/skip breakdown |

**Template Variables:**

| Variable | Source | Purpose |
|----------|--------|---------|
| `$model` | `SELECT DISTINCT model_name FROM robot_test_runs` | Filter all panels by model(s) |
| `$suite` | `SELECT DISTINCT test_suite FROM robot_test_runs` | Filter all panels by suite(s) |

Use the dropdowns at the top of the dashboard to filter by specific models or
suites. Multi-select is enabled — you can compare any subset of models.

### Creating Custom Panels

To add your own panels to Grafana:

1. Navigate to the dashboard
2. Click **Edit** (pencil icon)
3. Click **Add** > **Visualization**
4. Select the "RFC PostgreSQL" datasource
5. Write your SQL query (see [SQL Queries for Model Comparison](#sql-queries-for-model-comparison))
6. Choose the visualization type

Example — custom panel for model pass rate with confidence intervals:

```sql
SELECT
    model_name AS "Model",
    COUNT(*) AS "Runs",
    ROUND(AVG(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS "Avg Pass Rate %",
    ROUND(MIN(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS "Min %",
    ROUND(MAX(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS "Max %",
    ROUND(STDDEV(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS "Std Dev"
FROM test_runs
WHERE total_tests > 0
GROUP BY model_name
ORDER BY "Avg Pass Rate %" DESC;
```

---

## Superset Dashboards

### Accessing Superset

Open `http://localhost:8088` and log in with the credentials from `.env`
(default: `admin` / `changeme`).

### Pre-configured Dashboards

The bootstrap script creates the **RFC Test Health** dashboard, which
covers KPIs, host health, model performance, token efficiency, flaky
tests, and coverage.  All charts read from the lean `test_runs` /
`test_results` / `coverage_reports` tables; drill-down charts use the
`test_results_full` view to pull question / answer / grading text from
the artifact tables.

The legacy "Pipeline Health" and "Model Analytics" dashboards (backed
by the removed `pipeline_results`, `robot_dry_run_results`, and
`keyword_results` tables) were retired along with the schema
simplification.

### Using SQL Lab

Superset's SQL Lab provides an interactive SQL editor connected to the same
PostgreSQL database. Navigate to **SQL Lab** > **SQL Editor** and select the
"Robot Framework Results" database.

This is useful for ad-hoc queries, data exploration, and building custom
visualizations. See [SQL Queries for Model Comparison](#sql-queries-for-model-comparison)
for ready-to-use queries.

---

## Model Comparison Reports

This section covers every method available for comparing model performance:
CLI tools, Grafana panels, Superset dashboards, raw SQL, and Python API.

### CLI Comparison Tools

The `scripts/query_results.py` script provides quick command-line comparisons:

#### Performance Summary

```bash
uv run python scripts/query_results.py performance
```

Output:

```
Model Performance Summary
================================================================================
Model                | Runs | Pass Rate | Passed | Failed | Avg Duration
---------------------------------------------------------------------------
llama3.1:8b          | 15   | 87.5%     | 105    | 15     | 42.3s
mistral:7b           | 12   | 72.3%     | 78     | 30     | 38.1s
gemma2:9b            | 10   | 91.2%     | 83     | 8      | 55.7s
```

Filter by model:

```bash
uv run python scripts/query_results.py performance --model llama3.1:8b
```

#### Head-to-Head Comparison

```bash
uv run python scripts/query_results.py compare
```

Output:

```
Model Comparison
================================================================================

Best Performing: gemma2:9b
  Pass Rate: 91.2%
  Total Tests: 91

All Models:
  1. gemma2:9b: 91.2% (+0.0% vs best)
  2. llama3.1:8b: 87.5% (-3.7% vs best)
  3. mistral:7b: 72.3% (-18.9% vs best)
```

#### Recent Runs

```bash
uv run python scripts/query_results.py recent --limit 20
```

#### Test-Level History

Track a specific test's results across models over time:

```bash
uv run python scripts/query_results.py history "IQ 100 Basic Addition"
```

#### Export for External Analysis

```bash
uv run python scripts/query_results.py export --output results.json
```

### Grafana: Visual Model Comparison

Grafana's "RFC Test Results" dashboard provides the primary visual comparison
interface.

#### Using Template Variables for Comparison

1. Open `http://localhost:3000` and navigate to "RFC Test Results"
2. Use the **$model** dropdown at the top to select 2+ models
3. All panels filter to show only the selected models
4. The "Pass Rate by Model" bar chart provides the direct comparison

#### Key Comparison Panels

**Pass Rate by Model** (bar chart):

The most direct comparison. Shows each model's aggregate pass rate as a bar.
Color-coded: red < 70%, yellow < 90%, green >= 90%.

**Pass / Fail Over Time** (stacked bar, time series):

Shows how each model's pass/fail counts change over time. Useful for detecting
regressions (a model that was passing starts failing after a code change).

**Suite Duration Over Time** (line, time series):

Compares response speed across models. Slower models appear as higher lines.

**Individual Test Results** (table):

Drill into the latest run's per-test details: which specific questions each
model got right or wrong, and the grading reasons.

#### Custom Model Comparison Panels

To build deeper comparisons in Grafana, add panels using these SQL queries
(select "RFC PostgreSQL" as the datasource):

**Pass Rate Heatmap (Model x Suite):**

```sql
SELECT
    model_name AS "Model",
    test_suite AS "Suite",
    ROUND(AVG(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS "Pass Rate %"
FROM test_runs
WHERE total_tests > 0
GROUP BY model_name, test_suite
ORDER BY model_name, test_suite;
```

**Model Improvement Over Time:**

```sql
SELECT
    timestamp AS time,
    model_name AS metric,
    ROUND(passed::numeric / NULLIF(total_tests, 0) * 100, 1) AS "Pass Rate"
FROM test_runs
WHERE total_tests > 0
  AND $__timeFilter(timestamp)
ORDER BY timestamp;
```

**Head-to-Head: Which Tests Does Model A Pass That Model B Fails?**

```sql
WITH model_a AS (
    SELECT tr.test_name, tr.test_status
    FROM test_results tr
    JOIN test_runs r ON tr.run_id = r.id
    WHERE r.model_name = 'llama3.1:8b'
      AND r.id = (SELECT MAX(id) FROM test_runs WHERE model_name = 'llama3.1:8b')
),
model_b AS (
    SELECT tr.test_name, tr.test_status
    FROM test_results tr
    JOIN test_runs r ON tr.run_id = r.id
    WHERE r.model_name = 'mistral:7b'
      AND r.id = (SELECT MAX(id) FROM test_runs WHERE model_name = 'mistral:7b')
)
SELECT
    a.test_name AS "Test",
    a.test_status AS "Model A (llama3.1:8b)",
    b.test_status AS "Model B (mistral:7b)"
FROM model_a a
FULL OUTER JOIN model_b b ON a.test_name = b.test_name
WHERE a.test_status != b.test_status
ORDER BY a.test_name;
```

### Superset: Cross-Model Analytics

Superset's Model Analytics dashboard provides the deepest cross-model analysis.

#### Key Comparison Charts

**Model x Suite Performance** (table):

A matrix showing every model-suite combination with:
- `run_count` — how many times this model was tested on this suite
- `avg_pass_rate` — average pass rate across runs
- `avg_duration` — average execution time
- `total_passed` / `total_failed` — absolute counts
- `last_run` — when this combination was last tested

Example SQL:

```sql
SELECT
    model_name,
    test_suite,
    COUNT(*) AS run_count,
    AVG(CAST(passed AS FLOAT) / NULLIF(total_tests, 0) * 100) AS avg_pass_rate,
    AVG(duration_seconds) AS avg_duration,
    SUM(passed) AS total_passed,
    SUM(failed) AS total_failed,
    MAX(timestamp) AS last_run
FROM test_runs
WHERE total_tests > 0
GROUP BY model_name, test_suite
```

**Score Distribution** (bar):

Shows the distribution of scores (0 or 1) by model. A model with more 1s
(correct) and fewer 0s (incorrect) is performing better.

### SQL Queries for Model Comparison

These queries work in both Superset SQL Lab and Grafana panel editors. Connect
to the "Robot Framework Results" database (Superset) or "RFC PostgreSQL"
datasource (Grafana).

#### Overall Model Ranking

```sql
SELECT
    model_name,
    COUNT(*) AS total_runs,
    SUM(total_tests) AS total_tests,
    SUM(passed) AS total_passed,
    SUM(failed) AS total_failed,
    ROUND(AVG(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS avg_pass_rate,
    ROUND(AVG(duration_seconds), 1) AS avg_duration_s
FROM test_runs
WHERE total_tests > 0
GROUP BY model_name
ORDER BY avg_pass_rate DESC;
```

#### Per-Suite Breakdown

```sql
SELECT
    model_name,
    test_suite,
    COUNT(*) AS runs,
    SUM(passed) AS passed,
    SUM(failed) AS failed,
    ROUND(AVG(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS pass_rate
FROM test_runs
WHERE total_tests > 0
GROUP BY model_name, test_suite
ORDER BY test_suite, pass_rate DESC;
```

#### Most Commonly Failed Tests by Model

```sql
SELECT
    r.model_name,
    tr.test_name,
    COUNT(*) AS failure_count,
    MAX(r.timestamp) AS last_failure
FROM test_results tr
JOIN test_runs r ON tr.run_id = r.id
WHERE tr.test_status = 'FAIL'
GROUP BY r.model_name, tr.test_name
ORDER BY failure_count DESC
LIMIT 20;
```

#### Model Speed Comparison

```sql
SELECT
    model_name,
    COUNT(*) AS runs,
    ROUND(AVG(duration_seconds), 1) AS avg_duration_s,
    ROUND(MIN(duration_seconds), 1) AS min_duration_s,
    ROUND(MAX(duration_seconds), 1) AS max_duration_s,
    ROUND(STDDEV(duration_seconds), 1) AS stddev_duration_s
FROM test_runs
GROUP BY model_name
ORDER BY avg_duration_s ASC;
```

#### Regression Detection (Pass Rate Drop Between Latest Two Runs)

```sql
WITH ranked AS (
    SELECT
        model_name,
        test_suite,
        passed::numeric / NULLIF(total_tests, 0) * 100 AS pass_rate,
        ROW_NUMBER() OVER (
            PARTITION BY model_name, test_suite ORDER BY timestamp DESC
        ) AS rn
    FROM test_runs
    WHERE total_tests > 0
)
SELECT
    curr.model_name,
    curr.test_suite,
    ROUND(prev.pass_rate, 1) AS previous_run,
    ROUND(curr.pass_rate, 1) AS latest_run,
    ROUND(curr.pass_rate - prev.pass_rate, 1) AS delta
FROM ranked curr
JOIN ranked prev
  ON curr.model_name = prev.model_name
  AND curr.test_suite = prev.test_suite
  AND curr.rn = 1 AND prev.rn = 2
WHERE curr.pass_rate < prev.pass_rate
ORDER BY delta ASC;
```

#### Side-by-Side Test Results (Two Models)

```sql
SELECT
    COALESCE(a.test_name, b.test_name) AS test_name,
    a.test_status AS model_a_status,
    a.score AS model_a_score,
    b.test_status AS model_b_status,
    b.score AS model_b_score,
    CASE
        WHEN a.test_status = 'PASS' AND b.test_status = 'FAIL' THEN 'A wins'
        WHEN a.test_status = 'FAIL' AND b.test_status = 'PASS' THEN 'B wins'
        WHEN a.test_status = b.test_status THEN 'Tie'
        ELSE 'N/A'
    END AS winner
FROM (
    SELECT tr.test_name, tr.test_status, tr.score
    FROM test_results tr
    JOIN test_runs r ON tr.run_id = r.id
    WHERE r.model_name = 'MODEL_A_NAME'
      AND r.id = (SELECT MAX(id) FROM test_runs WHERE model_name = 'MODEL_A_NAME')
) a
FULL OUTER JOIN (
    SELECT tr.test_name, tr.test_status, tr.score
    FROM test_results tr
    JOIN test_runs r ON tr.run_id = r.id
    WHERE r.model_name = 'MODEL_B_NAME'
      AND r.id = (SELECT MAX(id) FROM test_runs WHERE model_name = 'MODEL_B_NAME')
) b ON a.test_name = b.test_name
ORDER BY test_name;
```

Replace `MODEL_A_NAME` and `MODEL_B_NAME` with actual model names (e.g.,
`llama3.1:8b`, `mistral:7b`).

#### Model Consistency (Standard Deviation of Pass Rate)

```sql
SELECT
    model_name,
    COUNT(*) AS runs,
    ROUND(AVG(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS avg_pass_rate,
    ROUND(STDDEV(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS pass_rate_stddev,
    ROUND(MIN(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS worst_run,
    ROUND(MAX(passed::numeric / NULLIF(total_tests, 0) * 100), 1) AS best_run
FROM test_runs
WHERE total_tests > 0
GROUP BY model_name
HAVING COUNT(*) >= 3
ORDER BY avg_pass_rate DESC;
```

### Programmatic Comparison

Use the Python API for integration with scripts, notebooks, or CI pipelines:

```python
from rfc.test_database import TestDatabase

# Connect to PostgreSQL
db = TestDatabase(database_url="postgresql://rfc:changeme@localhost:5433/rfc")

# Get performance stats for all models
stats = db.get_model_performance()
for stat in stats:
    print(
        f"{stat['model_name']}: "
        f"{stat['avg_pass_rate']:.1f}% pass rate, "
        f"{stat['total_runs']} runs, "
        f"{stat['avg_duration']:.1f}s avg"
    )

# Get performance for a specific model
llama_stats = db.get_model_performance("llama3.1:8b")

# Get recent runs
runs = db.get_recent_runs(limit=10)

# Get test-level history
history = db.get_test_history("IQ 100 Basic Addition")

# Export everything to JSON for external analysis
db.export_to_json("full_export.json")
```

---

## Database Schema Reference

See `docs/TEST_DATABASE.md` for the full schema narrative.  Summary:

### Physical Tables

#### `test_runs` — One row per suite execution (lean metrics only)

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-incrementing ID |
| `timestamp` | TIMESTAMP | When the test ran |
| `model_name` | VARCHAR(255) | LLM model identifier (e.g., `llama3.1:8b`) |
| `test_suite` | VARCHAR(255) | Suite name (`math`, `docker`, `safety`) |
| `total_tests` | INTEGER | Total test count |
| `passed` | INTEGER | Passed count |
| `failed` | INTEGER | Failed count |
| `skipped` | INTEGER | Skipped count |
| `duration_seconds` | DOUBLE PRECISION | Execution time |
| `git_commit` | VARCHAR(255) | Git commit SHA |
| `git_branch` | VARCHAR(255) | Git branch name |
| `hostname` | VARCHAR(255) | Machine name where tests ran |
| `rfc_version` | VARCHAR(50) | robotframework-chat version |

#### `test_results` — One row per individual test case (lean metrics)

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-incrementing ID |
| `run_id` | INTEGER FK | References `test_runs.id` |
| `test_name` | VARCHAR(500) | Test case name |
| `test_status` | VARCHAR(20) | `PASS`, `FAIL`, or `SKIP` |
| `score` | DOUBLE PRECISION | Graded score (0.0–1.0) |
| `tags` | TEXT | Comma-joined tag string |
| `tag_severity` | VARCHAR(20) | Parsed severity tag |
| `tag_tier` | INTEGER | Parsed tier tag |
| `tag_verify` | VARCHAR(50) | Parsed verify tag |
| `eval_count` | INTEGER | Tokens generated |
| `thinking_tokens` | INTEGER | Estimated tokens of `<think>` content |

#### `test_run_artifacts` — Per-run heavy archive

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | INTEGER PK / FK | One-to-one with `test_runs.id` |
| `output_xml_gz` | BYTEA | Gzip-compressed `output.xml` |
| `output_xml_source` | TEXT | Filesystem path the blob came from |

#### `test_result_artifacts` — Per-result heavy archive

Written only when at least one field is non-empty.

| Column | Type | Description |
|--------|------|-------------|
| `result_id` | INTEGER PK / FK | One-to-one with `test_results.id` |
| `question` | TEXT | Prompt sent to the model |
| `expected_answer` | TEXT | Expected correct answer |
| `actual_answer` | TEXT | Model's response |
| `grading_reason` | TEXT | Explanation from the grader |
| `thinking_text` | TEXT | Extracted `<think>` content |

#### `coverage_reports` — Code coverage snapshots

Populated by `scripts/collect_coverage.py`; one row per module per run.

### `test_results_full` view

Drill-down view for Superset.  JOINs `test_results` + `test_runs` and
LEFT-JOINs both artifact tables so dashboards can still fetch the
question / answer / grading / thinking text alongside metrics.

### Indexes

```sql
idx_test_runs_model           ON test_runs(model_name)
idx_test_runs_timestamp       ON test_runs(timestamp)
idx_test_runs_suite           ON test_runs(test_suite)
idx_test_results_run_id       ON test_results(run_id)
idx_coverage_reports_timestamp ON coverage_reports(timestamp)
idx_coverage_reports_git_commit ON coverage_reports(git_commit)
```

---

## Troubleshooting

### Services Fail to Start

```bash
# Check container status
docker compose ps

# View detailed logs
docker compose logs postgres
docker compose logs grafana
docker compose logs superset
```

**Common issues:**
- Port already in use: Change `POSTGRES_PORT`, `SUPERSET_PORT`, or
  `GRAFANA_PORT` in `.env`
- Docker not running: Start Docker Desktop or the Docker daemon
- Compose V1 syntax: Ensure you have `docker compose` (V2), not `docker-compose`

### Grafana Shows "No Data"

1. Check that PostgreSQL is healthy: `docker compose ps`
2. Verify data exists:
   ```bash
   psql $DATABASE_URL -c "SELECT COUNT(*) FROM test_runs;"
   ```
3. If tables are empty, run tests first: `make robot-math`
4. Check the Grafana datasource: **Configuration** > **Data Sources** > "RFC
   PostgreSQL" > **Test**
5. Ensure the time range in the dashboard covers your data (default: last 30
   days)

### Superset Shows Empty Charts

1. Verify the bootstrap completed:
   ```bash
   docker compose logs superset-init | tail -5
   ```
2. Check the database connection in Superset: **Data** > **Databases** >
   "Robot Framework Results" > **Test Connection**
3. Refresh dataset metadata: **Data** > **Datasets** > click each dataset >
   **Sync Columns**
4. Ensure data exists in the tables

### PostgreSQL Connection Refused

```bash
# Check if PostgreSQL is running
docker compose ps postgres

# Test the connection
psql $DATABASE_URL -c "SELECT 1;"

# Check the port mapping
docker compose port postgres 5432
```

If connecting from within Docker (Superset/Grafana), use `postgres:5432`.
If connecting from the host (test runner, scripts), use `localhost:5433`.

### Missing Dependencies

```bash
# SQLAlchemy / psycopg2 errors
uv sync --extra superset

# Full dev + superset dependencies
make install
```

---

## Maintenance

### Restarting Services

```bash
make docker-restart    # Rebuild and restart all services
make docker-down       # Stop all services
make docker-up         # Start all services
```

### Viewing Logs

```bash
make docker-logs       # Tail all logs
docker compose logs -f grafana     # Grafana only
docker compose logs -f superset    # Superset only
docker compose logs -f postgres    # PostgreSQL only
```

### Database Backup

```bash
# Dump the PostgreSQL database
docker compose exec postgres pg_dump -U rfc rfc > backup_$(date +%Y%m%d).sql

# Restore
cat backup_20260225.sql | docker compose exec -T postgres psql -U rfc rfc
```

### Database Maintenance

```bash
# Vacuum and analyze (reclaim space, update statistics)
psql $DATABASE_URL -c "VACUUM ANALYZE;"

# Check table sizes
psql $DATABASE_URL -c "
  SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
  FROM pg_stat_user_tables
  ORDER BY pg_total_relation_size(relid) DESC;
"
```

### Resetting Everything

```bash
# Stop services and remove volumes (destroys all data)
docker compose down -v

# Start fresh
make docker-up
make bootstrap
```
