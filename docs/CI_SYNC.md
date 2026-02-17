# CI Pipeline Sync

Syncs Robot Framework test artifacts from GitLab CI pipelines into the test
database (PostgreSQL or SQLite), making results available for Superset
dashboards and historical analysis.

## Quick Start

```bash
# 1. Set GitLab connection (skip if running inside GitLab CI)
export GITLAB_API_URL=https://gitlab.com
export GITLAB_PROJECT_ID=12345678

# 2. Optionally set a token for private projects
export GITLAB_TOKEN=glpat-xxxxxxxxxxxx

# 3. Sync recent pipelines to the database
make ci-sync-db

# 4. Verify data landed
make ci-verify-db
```

## How It Works

The sync bridge pulls test results from completed GitLab CI pipelines into
the same database that the in-pipeline `DbListener` writes to. This is
useful when you want to backfill results from pipelines that ran before
database archiving was configured, or when syncing from a remote GitLab
instance to a local development database.

### Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                      GitLab CI Pipeline                         │
│                                                                 │
│  test stage                          report stage               │
│  ┌──────────┐ ┌──────────┐          ┌──────────────────┐       │
│  │robot-math│ │robot-dock│ ...      │aggregate-results │       │
│  │          │ │          │          │                  │       │
│  │listener→ │ │listener→ │   ──►    │rebot merges XML  │       │
│  │ DB       │ │ DB       │          │import_test_      │       │
│  │          │ │          │          │ results.py → DB  │       │
│  └────┬─────┘ └────┬─────┘          └────────┬─────────┘       │
│       │             │                         │                 │
│       ▼             ▼                         ▼                 │
│   output.xml    output.xml            combined/output.xml       │
│   (artifact)    (artifact)              (artifact)              │
└───────┬─────────────┬─────────────────────────┬─────────────────┘
        │             │                         │
        └─────────────┼─────────────────────────┘
                      │
              ┌───────▼────────┐
              │  GitLab API    │
              │  /pipelines    │
              │  /jobs         │
              │  /artifacts    │
              └───────┬────────┘
                      │
         ┌────────────▼────────────┐
         │  sync_ci_results.py     │
         │                         │
         │  1. Fetch pipelines     │
         │  2. Fetch jobs per      │
         │     pipeline            │
         │  3. Download output.xml │
         │     to temp dir         │
         │  4. Deduplicate against │
         │     existing runs       │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  import_test_results.py │
         │                         │
         │  1. Parse output.xml    │
         │     (ET.parse)          │
         │  2. Extract metadata    │
         │     (model, commit,     │
         │      branch, pipeline)  │
         │  3. Extract per-test    │
         │     results (score,     │
         │     status, answers)    │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  TestDatabase           │
         │  (test_database.py)     │
         │                         │
         │  ┌───────────────────┐  │
         │  │ test_runs         │  │
         │  │ test_results      │  │
         │  │ models            │  │
         │  └───────────────────┘  │
         │                         │
         │  SQLite or PostgreSQL   │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  Apache Superset        │
         │  (dashboards, charts)   │
         └─────────────────────────┘
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| **GitLabArtifactFetcher** | `scripts/sync_ci_results.py` | API client that fetches pipelines, jobs, and downloads artifacts |
| **import_results** | `scripts/import_test_results.py` | Parses `output.xml` and writes `TestRun` + `TestResult` rows |
| **parse_output_xml** | `scripts/import_test_results.py` | Extracts suite stats, metadata, and per-test results from XML |
| **TestDatabase** | `src/rfc/test_database.py` | Database abstraction supporting SQLite and PostgreSQL |
| **sync_ci_results** | `scripts/sync_ci_results.py` | Orchestrates fetch → download → dedup → import loop |
| **verify_sync** | `scripts/sync_ci_results.py` | Validates data landed in the database after sync |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITLAB_API_URL` | Yes* | GitLab instance base URL (e.g., `https://gitlab.com`) |
| `GITLAB_PROJECT_ID` | Yes* | Numeric project ID (find it on the project settings page) |
| `GITLAB_TOKEN` | No | API token with `read_api` scope (required for private projects) |
| `DATABASE_URL` | No | PostgreSQL connection string (e.g., `postgresql://rfc:pass@localhost:5432/rfc`) |
| `CI_API_V4_URL` | Auto | Set automatically inside GitLab CI runners |
| `CI_PROJECT_ID` | Auto | Set automatically inside GitLab CI runners |

\* Not required when running inside GitLab CI (uses `CI_API_V4_URL` / `CI_PROJECT_ID`).

**Config resolution priority**: explicit constructor params → `CI_API_V4_URL`/`CI_PROJECT_ID` → `GITLAB_API_URL`/`GITLAB_PROJECT_ID`.

When `DATABASE_URL` is unset, the database defaults to SQLite at `data/test_history.db`.

## CLI Reference

All commands are run via `uv run python scripts/sync_ci_results.py <command>`.
Add `-v` for verbose logging to stderr.

### status

Check GitLab API connectivity:

```bash
$ make ci-status
API:     https://gitlab.com
Project: 12345678
Token:   set
Status:  OK - Connected to space-nomads/robotframework-chat
```

### list-pipelines

List recent successful pipelines:

```bash
$ make ci-list-pipelines
  #2330230622     success  claude-code-staging   https://gitlab.com/space-nomads/robotframework-chat/-/pipelines/2330230622
  #2330224840     success  main                  https://gitlab.com/space-nomads/robotframework-chat/-/pipelines/2330224840
  ...
```

Options: `-n <count>` (default 10), `--ref <branch>`.

### list-jobs

List jobs in a specific pipeline:

```bash
$ make ci-list-jobs PIPELINE=2330230622
  #  9876543     success  robot-math-tests
  #  9876544     success  robot-docker-tests
  #  9876545     success  robot-safety-tests
  #  9876546     success  aggregate-results
```

Options: `--scope <scope>` (default `success`).

### fetch-artifact

Download a single artifact file from a job:

```bash
$ make ci-fetch-artifact JOB=9876543
Downloaded: ./job_9876543_output.xml
```

Options: `--artifact-path <path>` (default `output.xml`), `-o <dir>` (default `.`).

### sync

Full sync: fetch recent pipelines, download artifacts, import into database,
and verify:

```bash
$ make ci-sync-db
Sync complete:
  Pipelines checked: 5
  Artifacts downloaded: 0
  Runs imported: 0
  Verify: PASS
```

When artifacts have already been imported (deduplication), counts are 0 — this
is expected. Options: `-n <count>` (default 5), `--ref <branch>`, `--db <path>`.

### verify

Check database contents:

```bash
$ make ci-verify-db
Database verification: PASS
  Recent runs: 1
  Latest timestamp: 2026-02-15 18:47:58.858173
  Models found: llama
```

Options: `--db <path>`, `--min-runs <n>` (default 1).

## Make Targets

| Target | Command | Purpose |
|--------|---------|---------|
| `ci-status` | `make ci-status` | Check GitLab API connectivity |
| `ci-list-pipelines` | `make ci-list-pipelines` | List recent pipelines |
| `ci-list-jobs` | `make ci-list-jobs PIPELINE=<id>` | List jobs in a pipeline |
| `ci-fetch-artifact` | `make ci-fetch-artifact JOB=<id>` | Download a single artifact |
| `ci-sync-db` | `make ci-sync-db` | Full sync + verify |
| `ci-verify-db` | `make ci-verify-db` | Check database contents |
| `ci-backfill` | `make ci-backfill` | **Deprecated** — Backfill all pipeline data |
| `ci-backfill-metadata` | `make ci-backfill-metadata` | **Deprecated** — Store pipeline metadata only |
| `ci-list-pipeline-results` | `make ci-list-pipeline-results` | List pipeline_results from database |

## Deduplication

The sync process avoids re-importing pipelines that are already in the
database. It works by:

1. Fetching the last 100 `test_runs` rows from the database
2. Collecting their `pipeline_url` values into a set
3. For each pipeline from the GitLab API, comparing its `web_url` against
   the set
4. Skipping the pipeline entirely if its URL is already present

This means running `make ci-sync-db` repeatedly is safe — it will only
import new pipelines.

## Artifact Path Resolution

Each CI job may store `output.xml` at different paths depending on the test
suite configuration. The sync tries each path in order until one succeeds:

```python
_ARTIFACT_PATHS = [
    "output.xml",
    "results/math/output.xml",
    "results/docker/output.xml",
    "results/safety/output.xml",
    "results/dashboard/output.xml",
]
```

When downloading, artifact paths containing `/` are sanitized to `_` in the
local filename (e.g., `results/math/output.xml` → `job_1001_results_math_output.xml`)
to avoid creating subdirectories in the temp directory.

## XML Parsing and Import

The `import_test_results.py` script handles the bridge between raw XML
artifacts and the database:

1. **Parse XML**: `parse_output_xml()` uses `xml.etree.ElementTree` to extract:
   - Suite name, test counts (pass/fail/skip), duration
   - Metadata items (model name, commit SHA, branch, pipeline URL, runner info)
   - Per-test results including status, score, question, expected/actual answers

2. **Resolve metadata**: The import function resolves metadata from multiple
   sources with fallback priority:
   - `output.xml` metadata items (e.g., `Model`, `Commit_SHA`, `Branch`)
   - Legacy GitLab-specific keys (e.g., `GitLab Commit`, `GitLab Branch`)
   - Environment variables (`CI_COMMIT_SHA`, `GITHUB_SHA`, etc.)

3. **Write to database**: Creates a `TestRun` row and associated `TestResult`
   rows via the `TestDatabase` API.

## Pipeline Results Dataset

Both `sync` and `backfill` store pipeline metadata in a `pipeline_results`
table. This table is available as a Superset dataset for dashboards that
track CI pipeline activity independently from test results.

### Schema

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing primary key |
| `pipeline_id` | INTEGER UNIQUE | GitLab pipeline ID |
| `status` | TEXT | Pipeline status (success, failed, etc.) |
| `ref` | TEXT | Branch or tag name |
| `sha` | TEXT | Git commit SHA |
| `web_url` | TEXT | Link to pipeline in GitLab |
| `created_at` | TEXT | Pipeline creation timestamp |
| `updated_at` | TEXT | Last update timestamp |
| `source` | TEXT | Pipeline trigger source (push, web, schedule, etc.) |
| `duration_seconds` | REAL | Pipeline duration |
| `queued_duration_seconds` | REAL | Time spent queued |
| `tag` | BOOLEAN | Whether this was a tag pipeline |
| `jobs_fetched` | INTEGER | Number of jobs found in pipeline |
| `artifacts_found` | INTEGER | Number of artifacts downloaded |
| `synced_at` | DATETIME | When this row was synced |

### Viewing stored pipeline data

```bash
$ make ci-list-pipeline-results
  #2330230622     success  claude-code-staging   jobs=4  artifacts=2  https://gitlab.com/...
  #2330224840     success  main                  jobs=4  artifacts=3  https://gitlab.com/...
```

## Backfill (Deprecated)

The `backfill` command fetches ALL pipelines from GitLab (paginated) and
imports their data. This is deprecated — prefer the `DbListener` for
real-time archiving of new pipelines. Use backfill only to import
historical pipelines that ran before database archiving was set up.

```bash
# Backfill all pipelines (metadata + artifacts)
make ci-backfill

# Backfill metadata only (faster, no artifact download)
make ci-backfill-metadata

# Backfill only successful pipelines on main
uv run python scripts/sync_ci_results.py backfill --status success --ref main
```

Options: `--ref <branch>`, `--status <status|all>` (default all),
`--metadata-only`, `--db <path>`.

The backfill command:

1. Paginates through all pipelines via the GitLab API (up to 2000)
2. Stores each pipeline as a `pipeline_results` row with metadata
3. Optionally downloads and imports `output.xml` artifacts
4. Deduplicates artifact imports against existing `test_runs`
5. Reports a summary with counts and any errors

## Error Handling

| Error Type | Behavior | Visibility |
|------------|----------|------------|
| API errors (HTTP 4xx/5xx) | Logged, returns empty list | `logging.warning` (use `-v`) |
| Network errors (DNS, timeout) | Logged, returns empty/None | `logging.warning` (use `-v`) |
| Artifact not found (404) | Logged, tries next path | `logging.debug` (use `-v`) |
| Import failures (bad XML) | Collected in `errors` list | Printed at end of sync |
| Artifact path with `/` | Sanitized to `_` in filename | Transparent |

The sync process never raises exceptions to the caller. It continues
processing remaining pipelines/jobs and returns a result dict with counts
and any errors encountered.

## Troubleshooting

### "0 artifacts downloaded, 0 runs imported" on every sync

This usually means all recent pipelines are already in the database
(deduplication is working). Run `make ci-verify-db` to confirm data exists.
To force re-processing, you would need to delete the corresponding
`test_runs` rows from the database.

### "GitLab API URL and project ID are required"

Set the environment variables:

```bash
export GITLAB_API_URL=https://gitlab.com
export GITLAB_PROJECT_ID=12345678
```

Find your project ID on the GitLab project settings page, or from the
project's general settings page (displayed near the top).

### "HTTP 401" on status check

Your `GITLAB_TOKEN` is invalid or expired. Generate a new one at
GitLab → User Settings → Access Tokens with `read_api` scope.

For public projects, the token is optional — try unsetting it:

```bash
unset GITLAB_TOKEN
make ci-status
```

### "No pipelines found"

Check that the project has successful pipelines:

```bash
# List all pipelines (not just successful)
uv run python scripts/sync_ci_results.py list-pipelines -v
```

If your pipelines are on a specific branch:

```bash
uv run python scripts/sync_ci_results.py list-pipelines --ref main
```

### Verbose debugging

Add `-v` to any CLI command for detailed logging to stderr:

```bash
uv run python scripts/sync_ci_results.py sync -v 2>sync.log
```

This shows API URLs being called, artifact download attempts, and
deduplication decisions.

## Test Coverage

Tests are in `tests/test_sync_ci_results.py` and
`tests/test_import_test_results.py` (103 tests total):

### sync_ci_results.py (71 tests)

- GitLabArtifactFetcher init, properties, trailing slash (9 tests)
- check_connection with OK, 401, 404, unreachable (5 tests)
- Pipeline/job/artifact fetching (11 tests)
- Paginated fetch_all_pipelines (3 tests)
- End-to-end sync workflow including error recording, multi-job, no-pipeline (9 tests)
- Pipeline metadata storage during sync (2 tests)
- verify_sync including threshold, null timestamp (5 tests)
- Backfill pipelines including metadata-only, dedup, error recording (7 tests)
- All CLI subcommand handlers including backfill and list-pipeline-results (17 tests)
- Helper function tests (3 tests)

### import_test_results.py

- RF timestamp parsing (ISO format, legacy format, empty string, None)
- output.xml parsing (single suite, nested suites, statistics extraction)
- Metadata extraction and fallback priority
- Per-test result extraction (status, score, question, answers)
- import_results end-to-end with database writes
- Edge cases (empty suites, missing metadata, malformed XML)

## Related Documentation

- [TEST_DATABASE.md](TEST_DATABASE.md) — Database schema, backends, query examples
- [GITLAB_CI_SETUP.md](GITLAB_CI_SETUP.md) — GitLab runner setup, pipeline stages, listeners
