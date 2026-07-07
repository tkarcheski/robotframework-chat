# Test Results Database

This document describes the SQL database for storing and analyzing Robot
Framework test results, with support for SQLite and PostgreSQL backends.

## Overview

The test database provides persistent storage for Robot Framework test
results, enabling:

- Historical tracking of model performance
- Comparison between models over time
- Analysis of test trends and patterns
- Visualization in Apache Superset dashboards
- Export for external analysis

## Backends

| Backend | When Used | Install |
|---------|-----------|---------|
| **SQLite** | Default when `DATABASE_URL` is not set | Built-in (no extra deps) |
| **PostgreSQL** | When `DATABASE_URL` is set to a `postgresql://` URL | `uv sync --extra superset` |

Backend selection is automatic based on the `DATABASE_URL` environment
variable:

```bash
# PostgreSQL (used with Superset)
export DATABASE_URL=postgresql://rfc:changeme@localhost:5433/rfc

# SQLite (default - no configuration needed)
# Stores to data/test_history.db
```

## How Results Get Into the Database

Results are archived automatically via the `DbListener` Robot Framework
listener:

```bash
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.git_metadata_listener.GitMetaData \
  robot/20__tier2/math/tests/
```

The `DbListener` hooks into Robot Framework's lifecycle:

1. `start_suite` — records start time, collects CI metadata
2. `end_test` — accumulates per-test results (name, status, score, lean
   metrics, plus archive fields captured via `RFC_DATA:` log messages)
3. `end_suite` — writes a `TestRun`, the associated `TestResult` rows,
   and per-run / per-result archive rows to the database
4. `close` — compresses the finalised `output.xml` and upserts it into
   `test_run_artifacts`

The `Makefile` targets and CI pipeline always attach both listeners.

You can also import results after the fact from `output.xml` files:

```bash
# Import single output.xml
uv run python scripts/import_test_results.py results/math/output.xml

# Import all output.xml files in directory (recursive)
uv run python scripts/import_test_results.py results/ --recursive

# Import with specific model name
uv run python scripts/import_test_results.py results/math/output.xml --model llama3.1
```

## Schema

The schema splits lean metrics from heavy archive data.  Dashboards hit
the lean tables directly; Superset drill-down joins the archive tables
through the `test_results_full` view.

### `test_runs` — lean per-suite metrics

One row per test suite execution.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing primary key |
| `timestamp` | DATETIME | When the test ran |
| `model_name` | TEXT | LLM model used (e.g., llama3, mistral) |
| `test_suite` | TEXT | Test suite name (math, docker, safety) |
| `total_tests` | INTEGER | Total test count |
| `passed` | INTEGER | Passed test count |
| `failed` | INTEGER | Failed test count |
| `skipped` | INTEGER | Skipped test count |
| `duration_seconds` | REAL | Test execution time in seconds |
| `git_commit` | TEXT | Git commit SHA |
| `git_branch` | TEXT | Git branch name |
| `hostname` | TEXT | Machine name where tests ran |
| `rfc_version` | TEXT | Version of robotframework-chat |

### `test_results` — lean per-test metrics

Individual test case results.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing primary key |
| `run_id` | INTEGER FK | Foreign key to `test_runs.id` |
| `test_name` | TEXT | Test case name |
| `test_status` | TEXT | PASS, FAIL, or SKIP |
| `score` | REAL | Graded score (0.0–1.0) if applicable |
| `tags` | TEXT | Comma-joined tag string |
| `tag_severity` | TEXT | Parsed severity tag |
| `tag_tier` | INTEGER | Parsed tier tag |
| `tag_verify` | TEXT | Parsed verify tag |
| `eval_count` | INTEGER | Tokens generated (from LLM metrics) |
| `thinking_tokens` | INTEGER | Estimated token count of `<think>` content |

### `test_run_artifacts` — per-run heavy archive

One row per `test_runs.id`.  Written by the listener at `close()` time
and by the importer at import time.  The `run_id` is the primary key
and FK to `test_runs.id` with `ON DELETE CASCADE`.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | INTEGER PK/FK | One-to-one with `test_runs.id` |
| `output_xml_gz` | BLOB / BYTEA | Gzip-compressed `output.xml` |
| `output_xml_source` | TEXT | Filesystem path the blob came from |

### `test_result_artifacts` — per-result heavy archive

One row per `test_results.id` (skipped entirely when every field is
empty).  The `result_id` is the primary key and FK to `test_results.id`
with `ON DELETE CASCADE`.

| Column | Type | Description |
|--------|------|-------------|
| `result_id` | INTEGER PK/FK | One-to-one with `test_results.id` |
| `question` | TEXT | Test question / prompt |
| `expected_answer` | TEXT | Expected correct answer |
| `actual_answer` | TEXT | Model's response (thinking tags stripped) |
| `grading_reason` | TEXT | Explanation from the grader |
| `thinking_text` | TEXT | Extracted `<think>` content |

### `test_results_full` view

Superset drill-down view — `JOIN test_runs` + `LEFT JOIN` both artifact
tables — so dashboards can still show per-test questions, answers, and
grading text alongside the lean metrics.  The column set is defined
once as `TEST_RESULTS_FULL_VIEW_BODY` in `src/rfc/test_database.py` and
is mirrored into `superset/bootstrap_dashboards.py`; a drift test keeps
the two in sync.

### Agentic Stack Tracker tables and `agentic_sessions_full` view

The Agentic Stack Tracker (issues #352/#358/#353) adds seven tables —
`agentic_harnesses`, `agentic_plugins`, `agentic_skills`,
`agentic_metrics` (EAV per-session/per-test metrics),
`agentic_decisions`, `dialog_recordings`, and `dialog_turns` — owned by
`HarnessDatabase` in `src/rfc/harness_db.py` (SQLite and PostgreSQL).
The Superset bootstrap creates the same tables with
`CREATE TABLE IF NOT EXISTS`, so either side may run first.

`agentic_sessions_full` denormalizes one row per harness session and
pre-pivots the EAV metrics (`tokens_in`, `tokens_out`, `latency_ms` →
`avg_latency_ms`, `grader_score` → `avg_grader_score`), plus a
`started_ts` timestamp cast for time-series charts.  The body is
defined once as `AGENTIC_SESSIONS_FULL_VIEW_BODY` in
`src/rfc/harness_db.py` and mirrored into
`superset/bootstrap_dashboards.py`; a drift test keeps the two in sync.

`make bootstrap` registers the tables, the view, and three virtual
datasets (`agentic_plugin_drift`, `agentic_skill_outcomes`,
`agentic_outcome_funnel`) as Superset datasets and builds the
**Agentic Stack Tracker** dashboard (slug `agentic-stack-tracker`) with
six panels: Harness Comparison, Plugin Drift, Skill SHA Heatmap, Token
Burn Rate, Outcome Funnel, and Latency vs Grader Score.

### `models`

LLM model metadata:

| Column | Type | Description |
|--------|------|-------------|
| `name` | TEXT PK | Model name (e.g., llama3:8b) |
| `sha256_digest` | TEXT | Model weights SHA256 from `/api/show` |
| `size_gb` | REAL | Model size in gigabytes |
| `quantization` | TEXT | e.g., Q4_K_M, Q8_0, FP16 |
| `architecture` | TEXT | e.g., llama, mistral, gemma |
| `context_length` | INTEGER | Max context window |
| `family` | TEXT | Model family |

### Upgrade semantics

When an older database starts up, the backend runs idempotent
`ALTER TABLE ... DROP COLUMN IF EXISTS` migrations that remove the old
heavy columns from `test_runs` / `test_results` and create the two
artifact tables.  **Legacy column data is not migrated** — historical
rows keep their metric columns but lose their heavy archive fields.
Start fresh if you need those fields for older runs.

---

## Querying Results

### CLI

```bash
# Initialize database (creates tables if needed)
uv run python -m rfc.test_database init

# View performance stats
uv run python -m rfc.test_database stats

# Export to JSON
uv run python -m rfc.test_database export [output.json]
```

### Script Queries

```bash
# View performance summary
uv run python scripts/query_results.py performance

# Show recent runs
uv run python scripts/query_results.py recent --limit 20

# View test history
uv run python scripts/query_results.py history "IQ 100 Basic Addition"

# Compare models
uv run python scripts/query_results.py compare

# Export to JSON
uv run python scripts/query_results.py export --output my_export.json
```

### Programmatic Access

```python
from rfc.test_database import TestDatabase, TestResult, TestRunArtifact

# SQLite (default)
db = TestDatabase()

# PostgreSQL
db = TestDatabase(database_url="postgresql://rfc:changeme@localhost:5433/rfc")

# Get recent runs
runs = db.get_recent_runs(limit=5)

# Get test history
history = db.get_test_history("IQ 100 Basic Addition")

# Fetch the per-run artifact (gzipped output.xml + source path)
artifact = db.get_test_run_artifact(runs[0]["id"])

# Export to JSON (archives are not included in the export)
db.export_to_json("export.json")
```

## Superset Visualization

When using PostgreSQL, results can be visualized in Apache Superset
dashboards.

### Setup

```bash
cp .env.example .env          # edit credentials
make docker-up                # start PostgreSQL + Redis + Superset
make bootstrap                # first-time init (creates admin, charts, dashboard)
open http://localhost:8088    # login with credentials from .env
```

### Pre-configured Charts

The bootstrap script creates these charts in Superset:

| Chart | Type | Description |
|-------|------|-------------|
| Pass Rate Over Time | Line | Test pass rate trend by model |
| Model Comparison | Bar | Side-by-side model pass rates |
| Test Results Breakdown | Pie | Pass/fail/skip distribution |
| Test Suite Duration Trend | Line | Execution time trends |
| Recent Test Runs | Table | Latest test run details |
| Failures by Test Name | Bar | Most common failing tests |

All charts are assembled into a "Robot Framework Test Results"
dashboard.  Detail charts for per-test question / answer / grading
text use the `test_results_full` view, which LEFT-JOINs the archive
tables.

## CI/CD Integration

The CI pipeline archives results at two levels:

```
test stage:  math ─────────┐   docker ────────┐   safety ────────┐
             listener→DB   │   listener→DB    │   listener→DB   │
             (per-suite)   │   (per-suite)    │   (per-suite)   │
                           ▼                  ▼                 ▼
report stage:          rebot merges output.xml files
                           │
                           ├── results/combined/report.html  (one unified report)
                           ├── results/combined/log.html
                           └── import → DB  (pipeline-level combined run)
```

1. **Per-suite archiving** (test stage): The `DbListener` on each test
   job archives results as each suite completes.
2. **Combined archiving** (report stage): `rebot` merges all
   `output.xml` files, then `import_test_results.py` imports the
   combined result.

Set `DATABASE_URL` as a CI secret (GitHub Actions) to archive to PostgreSQL.
When unset, archiving falls back to local SQLite.

## Database Maintenance

### SQLite

```bash
# Vacuum to reclaim space
sqlite3 data/test_history.db "VACUUM;"

# Create backup
cp data/test_history.db "data/test_history_$(date +%Y%m%d).db"
```

### PostgreSQL

```bash
# Connect to database
psql $DATABASE_URL

# Check table sizes
psql $DATABASE_URL -c "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC;"

# Vacuum
psql $DATABASE_URL -c "VACUUM ANALYZE;"
```

## Troubleshooting

### Database Locked (SQLite)

```bash
# Check for other processes
lsof data/test_history.db

# Wait and retry, or copy database
cp data/test_history.db data/test_history_temp.db
```

### PostgreSQL Connection Issues

```bash
# Check if PostgreSQL is running
make docker-logs

# Test connection
psql $DATABASE_URL -c "SELECT 1;"

# Check if tables exist
psql $DATABASE_URL -c "\dt"
```

### Missing SQLAlchemy

If you see `ImportError: sqlalchemy and psycopg2-binary are required`:

```bash
uv sync --extra superset
```
