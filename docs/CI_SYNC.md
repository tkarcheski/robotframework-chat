# CI Pipeline Sync

Fetches test artifacts from GitLab CI pipelines and imports them into the test database (PostgreSQL or SQLite).

## Architecture

```
GitLab CI Pipelines
    |
    v
GitLabArtifactFetcher  -->  /api/v4/projects/:id/pipelines
    |                        /api/v4/projects/:id/pipelines/:pid/jobs
    |                        /api/v4/projects/:id/jobs/:jid/artifacts/:path
    v
  output.xml (temp)
    |
    v
import_test_results.py  -->  TestDatabase (SQLite / PostgreSQL)
    |
    v
  Superset dashboards
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITLAB_API_URL` | Yes* | GitLab instance base URL |
| `GITLAB_PROJECT_ID` | Yes* | Numeric project ID |
| `GITLAB_TOKEN` | No | API token with `read_api` scope |
| `DATABASE_URL` | No | PostgreSQL connection string |
| `CI_API_V4_URL` | Auto | Set automatically inside GitLab CI runners |
| `CI_PROJECT_ID` | Auto | Set automatically inside GitLab CI runners |

\* Not required when running inside GitLab CI (uses `CI_API_V4_URL` / `CI_PROJECT_ID`).

## CLI Subcommands

```bash
# Check GitLab API connectivity
python scripts/sync_ci_results.py status

# List recent pipelines
python scripts/sync_ci_results.py list-pipelines [-n 10] [--ref main]

# List jobs in a pipeline
python scripts/sync_ci_results.py list-jobs <pipeline_id> [--scope success]

# Download a single artifact
python scripts/sync_ci_results.py fetch-artifact <job_id> [--artifact-path output.xml] [-o .]

# Full sync + verify
python scripts/sync_ci_results.py sync [-n 5] [--ref main] [--db path.db]

# Verify database contents
python scripts/sync_ci_results.py verify [--db path.db] [--min-runs 1]
```

Use `-v` for verbose logging to stderr.

## Make Targets

| Target | Command | Purpose |
|--------|---------|---------|
| `ci-status` | `make ci-status` | Check GitLab API connectivity |
| `ci-list-pipelines` | `make ci-list-pipelines` | List recent pipelines |
| `ci-list-jobs` | `make ci-list-jobs PIPELINE=<id>` | List jobs in a pipeline |
| `ci-fetch-artifact` | `make ci-fetch-artifact JOB=<id>` | Download a single artifact |
| `ci-sync-db` | `make ci-sync-db` | Full sync + verify |
| `ci-verify-db` | `make ci-verify-db` | Check database contents |

## Deduplication

The sync process avoids re-importing pipelines by comparing the `web_url` from the GitLab API against the `pipeline_url` column in the `test_runs` table. Pipelines already present in the last 100 runs are skipped.

## Error Handling

- API errors are logged via `logging.warning()` (visible with `-v`)
- Artifact download failures are logged via `logging.debug()`
- Import errors are collected in the sync result dict and printed at the end
- Artifact paths containing `/` (e.g., `results/log.html`) are sanitized to `_` to avoid filesystem path collisions

## Test Coverage

51 tests in `tests/test_sync_ci_results.py` covering:

- GitLabArtifactFetcher init, properties, trailing slash (9 tests)
- check_connection with OK, 401, 404, unreachable (5 tests)
- Pipeline/job/artifact fetching (11 tests)
- End-to-end sync workflow including error recording, multi-job, no-pipeline (8 tests)
- verify_sync including threshold, null timestamp (5 tests)
- All 6 CLI subcommand handlers (13 tests)
