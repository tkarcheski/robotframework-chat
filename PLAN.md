# Plan: Database Redesign — Output.xml as Source of Truth

## Problem

The current database has 13 tables and 48+ charts that duplicate what Robot
Framework already provides in `output.xml`. Data isn't reaching Superset because
`DATABASE_URL` is silently unset, but even when it works, the schema is bloated
and disconnected from RF fundamentals.

## Design Principle

**The database is an index into Robot Framework runs, not a replacement for RF
reporting.** `output.xml` is the source of truth. The database stores:

1. A compressed copy of `output.xml` (self-contained, always accessible)
2. An HTTP URL to the original `output.xml` (for web access)
3. Run-level and test-level summaries for Superset charting

Everything else — keyword timing, messages, tags, metadata — lives in `output.xml`
and can be extracted on demand.

---

## New Schema (2 tables)

### `test_runs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `timestamp` | DATETIME NOT NULL | When the suite started |
| `model_name` | TEXT NOT NULL | LLM model under test |
| `test_suite` | TEXT NOT NULL | Robot Framework suite name |
| `total_tests` | INTEGER | Count |
| `passed` | INTEGER | Count |
| `failed` | INTEGER | Count |
| `skipped` | INTEGER | Count |
| `duration_seconds` | REAL | Wall-clock suite duration |
| `git_commit` | TEXT | SHA at time of run |
| `git_branch` | TEXT | Branch at time of run |
| `hostname` | TEXT | Machine that ran the tests |
| `rfc_version` | TEXT | Version of rfc package |
| `output_xml_url` | TEXT | HTTP URL to output.xml (nullable) |
| `output_xml_gz` | BLOB | gzip-compressed output.xml |

**Indexes:** `(model_name)`, `(timestamp)`, `(test_suite)`

### `test_results`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `run_id` | INTEGER FK | → test_runs.id ON DELETE CASCADE |
| `test_name` | TEXT NOT NULL | Test case name |
| `test_status` | TEXT NOT NULL | PASS / FAIL / SKIP |
| `score` | INTEGER | From `score:N` tag (nullable) |
| `question` | TEXT | Test documentation / prompt |
| `expected_answer` | TEXT | Expected LLM response |
| `actual_answer` | TEXT | Actual LLM response |
| `grading_reason` | TEXT | Why the grade was given |
| `rfc_version` | TEXT | Version of rfc package |

**Indexes:** `(run_id)`

---

## Tables Being Dropped (11 tables)

| Table | Reason |
|-------|--------|
| `keyword_results` | Fully in output.xml |
| `ollama_metrics` | Extractable from output.xml |
| `host_info` | hostname column on test_runs suffices |
| `models` | model_name column on test_runs suffices |
| `pipeline_results` | GitLab CI metadata, not core RF |
| `robot_dry_run_results` | Not core |
| `analytics_model_trends` | Recomputable / Superset can do this |
| `analytics_test_stability` | Recomputable |
| `analytics_model_comparison` | Recomputable |
| `analytics_regression_alerts` | Recomputable |
| `analytics_performance_fingerprints` | Recomputable |

---

## Files to Change

### Core (rewrite)

| File | Action | Details |
|------|--------|---------|
| `src/rfc/test_database.py` | **Rewrite** | 2 tables only. Both SQLite and SQLAlchemy backends. Add `output_xml_gz` BLOB column. Remove all dropped-table methods. |
| `src/rfc/db_listener.py` | **Rewrite** | Capture output.xml at end_suite, gzip it, store blob + URL. Remove keyword tracking, ollama metrics accumulation. **Fail loudly** if DATABASE_URL is unset (eager validation in start_suite). |
| `superset/bootstrap_dashboards.py` | **Rewrite** | 2 core tables, simplified virtual datasets, rebuilt charts/dashboards. |

### Delete

| File | Reason |
|------|--------|
| `src/rfc/analytics.py` | Dropped entirely |
| `tests/test_analytics.py` (if exists) | No module to test |
| `src/rfc/result_importer.py` | Rewrite to match new schema (no keyword/ollama import) |

### Simplify

| File | Change |
|------|--------|
| `src/rfc/superset_keywords.py` | Remove references to dropped tables |
| `scripts/run_local_models.py` | Remove DB verification for dropped tables; add pre-flight DATABASE_URL check |
| `scripts/cron_run_local_models.sh` | Source `.env` before running |
| `scripts/diagnose_superset_db.py` | Update table list |
| `Makefile` | Remove analytics targets |

### Tests

| File | Change |
|------|--------|
| `tests/test_db_listener.py` | Update for new schema, test output.xml blob capture |
| `tests/test_test_database.py` | Update for 2-table schema |
| `tests/test_result_importer.py` | Update for simplified import |
| `robot/superset/tests/connection.robot` | Update table expectations |

---

## Migration Strategy

**Purge and rebuild.** No migration — the user explicitly asked to purge previous
data. The bootstrap script will `DROP TABLE IF EXISTS` all old tables and create
the new 2-table schema fresh.

---

## Data Flow (New)

```
Robot Test Execution
│
├─→ DbListener.start_suite()
│   └─→ Validate DATABASE_URL exists → FAIL LOUDLY if not
│
├─→ Tests run normally, DbListener captures RFC_DATA: messages
│
├─→ DbListener.end_suite()
│   ├─→ Read output.xml from Robot's output directory
│   ├─→ gzip compress it
│   ├─→ INSERT into test_runs (with output_xml_gz blob + URL)
│   ├─→ INSERT into test_results (one per test case)
│   └─→ Log: "archived N results + output.xml (XMB) to PostgreSQL"
│
└─→ Superset queries test_runs + test_results for dashboards
    └─→ output.xml accessible via URL column or by decompressing blob
```

---

## Superset Dashboards (Rebuilt)

### Dashboard 1: Test Results
- Pass rate over time by model (line chart)
- Model comparison — pass rate (bar chart)
- Test status breakdown (pie chart)
- Suite duration trend (line chart)
- Recent test runs (table — includes output_xml_url as clickable link)
- Failures by test name (bar chart)

### Dashboard 2: Model Performance
- Pass rate by model (bar chart)
- Avg duration by model (bar chart)
- Tests per model (bar chart)
- Score distribution (bar chart)
- Test results detail (table with output_xml_url link)

That's it. 2 dashboards, ~11 charts. Not 6 dashboards and 48 charts.
