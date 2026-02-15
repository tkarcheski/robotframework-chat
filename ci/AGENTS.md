# CI Agents

Scripts in `ci/` are thin shell wrappers that load environment, validate config, and delegate to Python modules. Each maps to a `make ci-*` target.

## Agent Inventory

| Script | Make Target | Purpose |
|--------|-------------|---------|
| `lint.sh` | `ci-lint` | Run ruff, mypy, pre-commit checks |
| `test.sh` | `ci-test` | Run Robot Framework test suites with health checks |
| `generate.sh` | `ci-generate` | Generate child pipeline YAML |
| `report.sh` | `ci-report` | Generate repo metrics, optionally post to MR |
| `sync.sh` | `ci-sync` | Mirror repo to GitHub |
| `sync_db.sh` | `ci-sync-db` | Sync GitLab CI artifacts to database |
| `deploy.sh` | `ci-deploy` | Deploy Superset to remote host |
| `test_dashboard.sh` | `ci-test-dashboard` | Run dashboard pytest/Playwright tests |
| `review.sh` | `ci-review` | Run Claude Code review |

## Artifact Sync Agents

The `sync_db.sh` wrapper exposes individual subcommands for the artifact pipeline:

| Subcommand | Make Target | Purpose |
|------------|-------------|---------|
| `status` | `ci-status` | Check GitLab API connectivity |
| `list-pipelines` | `ci-list-pipelines` | List recent pipelines |
| `list-jobs <id>` | `ci-list-jobs` | List jobs in a pipeline |
| `fetch-artifact <id>` | `ci-fetch-artifact` | Download a job artifact |
| `sync` | `ci-sync-db` | Full sync (fetch + import + verify) |
| `verify` | `ci-verify-db` | Verify database contents |

## Adding a New Agent

1. Create `ci/<name>.sh` with `set -euo pipefail` and `.env` loading
2. Add a `ci-<name>:` target to `Makefile`
3. Add the corresponding job to `.gitlab-ci.yml` if it should run in CI
4. Update this file
