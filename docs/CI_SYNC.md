# CI Artifact Sync

Fetch Robot Framework `output.xml` artifacts from GitLab CI pipelines and import them into the test database.

## Problem

Tests run in GitLab CI produce `output.xml` artifacts, but those results are only accessible through the GitLab UI. The dashboard's `PipelineMonitor` displays pipeline status but cannot reliably pull artifacts into the local database for analysis and Superset dashboards.

## Solution

A standalone CLI (`scripts/sync_ci_results.py`) with individual subcommands for each step of the artifact fetch pipeline:

```
GitLab API                          Local Database
+-----------+    list-pipelines     +---------------+
| Pipelines | ───────────────────>  | (filter)      |
+-----------+                       +-------+-------+
      |          list-jobs                  |
      v                                    v
+-----------+    fetch-artifact     +---------------+
|   Jobs    | ───────────────────>  | output.xml    |
+-----------+                       +-------+-------+
                                            |
                                            v  import
                                    +---------------+
                                    | test_runs     |
                                    | test_results  |
                                    +---------------+
```

## Quick Start

```bash
# Check GitLab connection
make ci-status

# See what's available
make ci-list-pipelines
make ci-list-jobs PIPELINE=12345

# Full sync (fetch + import + verify)
make ci-sync-db

# Verify database
make ci-verify-db
```

## Commands

### `make ci-status`

Test GitLab API connectivity and show configuration:

```
GitLab CI Status
  API URL:     https://gitlab.com
  Project ID:  77444874
  Token:       configured
  Connection:  OK
  Project:     space-nomads/robotframework-chat
```

### `make ci-list-pipelines`

List recent successful pipelines:

```
ID           Status     Branch               SHA        URL
------------------------------------------------------------------------
1234         success    main                 abc12345   https://...
1235         success    feature/x            def67890   https://...
```

Options:
- `REF=main` -- filter by branch
- `LIMIT=20` -- number of pipelines to show

### `make ci-list-jobs PIPELINE=1234`

List jobs from a specific pipeline:

```
Job ID       Name                      Status     Duration
------------------------------------------------------------
5001         test-math                 success    120s
5002         test-docker               success    85s
```

### `make ci-fetch-artifact JOB=5001`

Download `output.xml` from a specific job:

```
Downloaded: ./job_5001_output.xml
```

Options:
- `ARTIFACT=results/log.html` -- download a different file
- `OUT=tmp/` -- output directory

### `make ci-sync-db`

Full workflow: fetch recent pipelines, download artifacts, import to database, verify.

### `make ci-verify-db`

Check database contents:

```
Database verification: PASS
  Recent runs: 15
  Latest timestamp: 2026-02-15 18:47:58
  Models found: llama3, mistral
```

## Python CLI

All commands are also available via the Python script directly:

```bash
# Subcommands
uv run python scripts/sync_ci_results.py status
uv run python scripts/sync_ci_results.py list-pipelines -n 20 --ref main
uv run python scripts/sync_ci_results.py list-jobs 12345
uv run python scripts/sync_ci_results.py fetch-artifact 67890 -o tmp/
uv run python scripts/sync_ci_results.py sync -n 10 --ref main --dry-run
uv run python scripts/sync_ci_results.py verify

# Verbose mode (log API calls to stderr)
uv run python scripts/sync_ci_results.py -v sync
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITLAB_API_URL` | Yes* | GitLab instance base URL |
| `GITLAB_PROJECT_ID` | Yes* | Numeric project ID |
| `GITLAB_TOKEN` | No | API token with `read_api` scope |
| `DATABASE_URL` | No | PostgreSQL URL (default: SQLite) |

*Inside GitLab CI, `CI_API_V4_URL` and `CI_PROJECT_ID` are used automatically.

### Resolution Priority

1. Explicit parameters (constructor / CLI args)
2. `CI_API_V4_URL` / `CI_PROJECT_ID` (GitLab CI environment)
3. `GITLAB_API_URL` / `GITLAB_PROJECT_ID` (env vars / `.env` file)

## Deduplication

The sync checks existing `pipeline_url` values in the database and skips pipelines that have already been imported. This makes it safe to run `make ci-sync-db` repeatedly.

## Architecture

```
ci/sync_db.sh                     Shell wrapper (env loading, subcommand routing)
  |
  v
scripts/sync_ci_results.py        CLI + GitLabArtifactFetcher + sync orchestration
  |
  v
scripts/import_test_results.py    XML parsing + TestRun/TestResult creation
  |
  v
src/rfc/test_database.py          Database abstraction (SQLite / PostgreSQL)
```

The dashboard's `PipelineMonitor` (in `dashboard/monitoring.py`) handles real-time pipeline status display separately. The sync CLI handles the artifact-to-database pipeline.
