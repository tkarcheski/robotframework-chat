# CI Features Matrix

Feature inventory with implementation status and test coverage.

## Pipeline Features

| Feature | Script | Tests | Status |
|---------|--------|-------|--------|
| Ruff lint + format checks | `ci/lint.sh` | - | Active |
| Robot Framework test execution | `ci/test.sh` | - | Active |
| Dynamic pipeline generation | `ci/generate.sh` | - | Active |
| Repo metrics report | `ci/report.sh` | - | Active |
| GitHub mirror sync | `ci/sync.sh` | - | Active |
| CI artifact sync to DB | `scripts/sync_ci_results.py` | 51 | Active |
| Superset deployment | `ci/deploy.sh` | - | Active |
| Dashboard tests (pytest) | `ci/test_dashboard.sh` | - | Active |
| Dashboard tests (Playwright) | `ci/test_dashboard.sh` | - | Active |
| AI code review | `ci/review.sh` | - | Active |

## CI Sync Subcommands

| Subcommand | Make Target | Tests | Purpose |
|------------|-------------|-------|---------|
| `status` | `make ci-status` | 2 | Check GitLab API connectivity |
| `list-pipelines` | `make ci-list-pipelines` | 2 | List recent pipelines |
| `list-jobs` | `make ci-list-jobs PIPELINE=<id>` | 2 | List jobs in a pipeline |
| `fetch-artifact` | `make ci-fetch-artifact JOB=<id>` | 2 | Download a single artifact |
| `sync` | `make ci-sync-db` | 2 | Full sync + verify |
| `verify` | `make ci-verify-db` | 2 | Check database contents |

## CI Sync Test Coverage Breakdown

| Area | Tests |
|------|-------|
| GitLabArtifactFetcher init, properties, trailing slash | 9 |
| check_connection (OK, 401, 404, unreachable) | 5 |
| Pipeline/job/artifact fetching | 11 |
| End-to-end sync workflow | 8 |
| verify_sync | 5 |
| CLI subcommand handlers | 13 |
| **Total** | **51** |

## Bugs Fixed (This Release)

| Bug | File:Line | Fix |
|-----|-----------|-----|
| Dedup key mismatch | `sync_ci_results.py:269` | `gitlab_pipeline_url` -> `pipeline_url` |
| Silent API errors | `sync_ci_results.py` (all handlers) | Added `_log.warning()` / `_log.debug()` |
| Artifact path collision | `sync_ci_results.py:232` | Sanitize `/` -> `_` in filenames |
