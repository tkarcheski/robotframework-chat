# Test Results Database

This document describes the SQL database for storing and analyzing Robot Framework test results, with support for SQLite and PostgreSQL backends.

## Overview

The test database provides persistent storage for Robot Framework test results, enabling:
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

Backend selection is automatic based on the `DATABASE_URL` environment variable:

```bash
# PostgreSQL (used with Superset)
export DATABASE_URL=postgresql://rfc:changeme@localhost:5433/rfc

# SQLite (default - no configuration needed)
# Stores to data/test_history.db
```

## How Results Get Into the Database

Results are archived automatically via the `DbListener` Robot Framework listener:

```bash
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.git_metadata_listener.GitMetaData \
  robot/math/tests/
```

The `DbListener` hooks into Robot Framework's lifecycle:
1. `start_suite` — records start time, collects CI metadata
2. `end_test` — accumulates per-test results (name, status, score)
3. `end_suite` — at the top-level suite, writes a `TestRun` and all `TestResult` rows to the database

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

### Tables

#### `test_runs`
One row per test suite execution (or per pipeline-level combined run):

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing primary key |
| `timestamp` | DATETIME | When the test ran |
| `model_name` | TEXT | LLM model used (e.g., llama3, mistral) |
| `model_release_date` | TEXT | Model release date from metadata |
| `model_parameters` | TEXT | Model size (e.g., 8B, 70B) |
| `test_suite` | TEXT | Test suite name (math, docker, safety) |
| `git_commit` | TEXT | Git commit SHA |
| `git_branch` | TEXT | Git branch name |
| `pipeline_url` | TEXT | Link to CI pipeline |
| `runner_id` | TEXT | CI runner identifier |
| `runner_tags` | TEXT | Runner capabilities |
| `total_tests` | INTEGER | Total test count |
| `passed` | INTEGER | Passed test count |
| `failed` | INTEGER | Failed test count |
| `skipped` | INTEGER | Skipped test count |
| `duration_seconds` | REAL | Test execution time in seconds |
| `rfc_version` | TEXT | Version of robotframework-chat |

#### `test_results`
Individual test case results:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing primary key |
| `run_id` | INTEGER FK | Foreign key to `test_runs.id` |
| `test_name` | TEXT | Test case name |
| `test_status` | TEXT | PASS, FAIL, or SKIP |
| `score` | INTEGER | Graded score (0 or 1) if applicable |
| `question` | TEXT | Test question/prompt |
| `expected_answer` | TEXT | Expected correct answer |
| `actual_answer` | TEXT | Model's response |
| `grading_reason` | TEXT | Explanation from grader |

#### `models`
Model metadata:

| Column | Type | Description |
|--------|------|-------------|
| `name` | TEXT PK | Model identifier |
| `full_name` | TEXT | Human-readable name |
| `organization` | TEXT | Model creator |
| `release_date` | TEXT | Model release date |
| `parameters` | TEXT | Model size |
| `last_tested` | DATETIME | Timestamp of last test |

### Planned Schema Changes (Owner-Confirmed 2026-02-19)

> See `humans/TODO.md` § Database & Schema Changes for the full list.

The following additions are planned for the database schema:

**`test_runs` — new columns:**

| Column | Type | Description |
|--------|------|-------------|
| `temperature` | REAL | Inference temperature used |
| `seed` | INTEGER | Random seed for reproducibility |
| `top_p` | REAL | Top-p sampling parameter |
| `top_k` | INTEGER | Top-k sampling parameter |
| `cost_seconds` | REAL | Wall-clock time (local cost) |
| `cost_dollars` | REAL NULL | Dollar cost (cloud/OpenRouter) |
| `suite_version` | TEXT | Git SHA of the `.robot` file |
| `node_hostname` | TEXT | Which hardware node ran this |
| `hardware_gpu` | TEXT | GPU/TPU model (e.g., "RTX 4090") |
| `hardware_vram_gb` | REAL | VRAM in GB |

**`models` — new columns:**

| Column | Type | Description |
|--------|------|-------------|
| `sha256_digest` | TEXT | Model weights SHA256 from `/api/show` |
| `size_gb` | REAL | Model size in gigabytes |
| `quantization` | TEXT | e.g., Q4_K_M, Q8_0, FP16 |
| `architecture` | TEXT | e.g., llama, mistral, gemma |
| `context_length` | INTEGER | Max context window |
| `family` | TEXT | Model family |
| `license` | TEXT | Model license |

**`llm_performance` — new table (or columns on `test_results`):**

| Column | Type | Description |
|--------|------|-------------|
| `eval_count` | INTEGER | Tokens generated |
| `eval_duration` | INTEGER | Time to generate (nanoseconds) |
| `prompt_eval_count` | INTEGER | Prompt tokens processed |
| `prompt_eval_duration` | INTEGER | Time to process prompt (ns) |
| `load_duration` | INTEGER | Time to load model (ns) |
| `total_duration` | INTEGER | Total request time (ns) |
| `tokens_per_second` | REAL | Computed: eval_count / (eval_duration / 1e9) |

**Data retention:** 90-day rolling window. Older data archived to compressed exports.

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
from rfc.test_database import TestDatabase

# SQLite (default)
db = TestDatabase()

# PostgreSQL
db = TestDatabase(database_url="postgresql://rfc:changeme@localhost:5433/rfc")

# Get performance stats
stats = db.get_model_performance()
for stat in stats:
    print(f"{stat['model_name']}: {stat['avg_pass_rate']:.1f}%")

# Get recent runs
runs = db.get_recent_runs(limit=5)

# Get test history
history = db.get_test_history("IQ 100 Basic Addition")

# Export to JSON
db.export_to_json("export.json")
```

## Superset Visualization

When using PostgreSQL, results can be visualized in Apache Superset dashboards.

### Setup

```bash
cp .env.example .env          # edit credentials
make docker-up                # start PostgreSQL + Redis + Superset
make bootstrap                # first-time init (creates admin, charts, dashboard)
open http://localhost:8088     # login with credentials from .env
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

All charts are assembled into a "Robot Framework Test Results" dashboard.

## CI/CD Integration

The GitLab CI pipeline archives results at two levels:

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

1. **Per-suite archiving** (test stage): The `DbListener` on each test job archives results as each suite completes
2. **Combined archiving** (report stage): `rebot` merges all `output.xml` files, then `import_test_results.py` imports the combined result

Set `DATABASE_URL` in GitLab CI/CD variables to archive to PostgreSQL. When unset, archiving falls back to local SQLite.

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
