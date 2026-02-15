# CI Features

Feature matrix for the CI/CD pipeline and local development tooling.

## Pipeline Stages

| Stage | Job | Trigger | Description |
|-------|-----|---------|-------------|
| sync | `mirror-to-github` | Push to main | Mirror repo to GitHub |
| lint | `lint` | All pushes/MRs | ruff + mypy + pre-commit |
| generate | `generate-pipeline` | All pushes/MRs | Generate child pipeline YAML |
| test | `run-regular-tests` | Generated | Robot Framework test suites |
| test | `run-dynamic-tests` | Generated | Dynamic test discovery |
| test | `dashboard-pytest` | All pushes/MRs | Dashboard unit tests |
| test | `dashboard-playwright` | All pushes/MRs | Dashboard browser tests |
| report | `repo-metrics` | Push to main | Generate repo metrics |
| deploy | `deploy-superset` | Manual/push | Deploy Superset dashboards |
| review | `opencode-review` | MR | Claude Code review |

## Artifact Sync (`make ci-sync-db`)

Fetch `output.xml` artifacts from GitLab CI and import into the test database.

### Features

| Feature | Status | Details |
|---------|--------|---------|
| Fetch pipelines | Done | Filter by branch, status, limit |
| Fetch jobs | Done | Per-pipeline job listing |
| Download artifacts | Done | Single-file download by job ID |
| Import to database | Done | Parse output.xml, create TestRun + TestResult |
| Deduplication | Done | Skip already-imported pipelines by `pipeline_url` |
| Verification | Done | Check database contents post-sync |
| Connection check | Done | Test GitLab API connectivity |
| Dry run | Done | Preview what would be synced |
| Verbose logging | Done | `-v` flag for API call debugging |
| SQLite backend | Done | Default local storage |
| PostgreSQL backend | Done | Via `DATABASE_URL` for Superset |
| CLI subcommands | Done | `status`, `list-pipelines`, `list-jobs`, `fetch-artifact`, `sync`, `verify` |
| Makefile targets | Done | `ci-status`, `ci-list-pipelines`, `ci-list-jobs`, `ci-fetch-artifact`, `ci-verify-db` |

### Test Coverage

| Component | Tests | File |
|-----------|-------|------|
| GitLabArtifactFetcher init | 9 | `tests/test_sync_ci_results.py` |
| check_connection | 5 | `tests/test_sync_ci_results.py` |
| fetch_recent_pipelines | 4 | `tests/test_sync_ci_results.py` |
| fetch_pipeline_jobs | 3 | `tests/test_sync_ci_results.py` |
| download_job_artifact | 4 | `tests/test_sync_ci_results.py` |
| sync_ci_results (e2e) | 8 | `tests/test_sync_ci_results.py` |
| verify_sync | 5 | `tests/test_sync_ci_results.py` |
| CLI subcommands | 13 | `tests/test_sync_ci_results.py` |
| **Total** | **51** | |

## Test Database

| Feature | Status | Details |
|---------|--------|---------|
| SQLite backend | Done | Default at `data/test_history.db` |
| PostgreSQL backend | Done | Via `DATABASE_URL` |
| DbListener | Done | Auto-archive during test runs |
| GitMetaData listener | Done | CI platform detection |
| Schema migrations | Done | Renames `gitlab_*` -> `git_*` / `pipeline_url` |
| JSON export | Done | `TestDatabase.export_to_json()` |

## Dashboard

| Feature | Status | Details |
|---------|--------|---------|
| Pipeline monitoring | Done | Real-time GitLab pipeline status |
| Job monitoring | Done | Per-pipeline job details |
| Ollama host monitoring | Done | Health + running model tracking |
| Auto-detection | Done | Git remote -> GitLab project ID |
| Artifact upload status | Done | Badge showing which pipelines are in DB |
