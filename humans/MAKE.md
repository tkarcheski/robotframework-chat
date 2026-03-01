# Make Targets — robotframework-chat

This project is driven primarily via `make`. The most important targets are:

```bash
make help
```

## Test Execution

- `make robot`
  Run all Robot Framework test suites.

- `make robot-math`
  Run math tests (Robot Framework).

- `make robot-docker`
  Run Docker tests (Robot Framework).

- `make robot-safety`
  Run safety tests (Robot Framework).

- `make robot-math-import`
  Run math tests then import results (continues on test failures).

- `make robot-import`
  Run all tests then import results (continues on test failures).

- `make robot-dryrun`
  Validate all Robot tests (dry run, no execution).

## Results & Model Discovery

- `make import`
  Import results from `output.xml` files.
  Example:

  ```bash
  make import RESULTS_DIR=results/
  ```

- `make send-results`
  Send results to remote server via `rsync`.
  Requires `RESULTS_SERVER_*` environment variables.

- `make discover-local-nodes`
  Scan network for Ollama nodes (online/offline status).

- `make discover-local-models`
  Discover Ollama nodes and list their models.

- `make run-local-models`
  Run test suites against every model on every local node.
  - `ITERATIONS=-1`: run forever
  - `ITERATIONS=0`: stop on first error

## Code Quality

- `make code-quality-lint`
  Run `ruff` linter.

- `make code-quality-format`
  Auto-format code.

- `make code-quality-typecheck`
  Run `mypy` type checker.

- `make code-quality-check`
  Run all code quality checks.

- `make code-quality-coverage`
  Run `pytest` with coverage report.

- `make code-quality-audit`
  Audit dependencies for known vulnerabilities.

## Services & Dashboards

- `make docker-up`
  Start PostgreSQL + Redis + Superset + Grafana.

- `make docker-down`
  Stop all services.

- `make docker-restart`
  Rebuild images and restart all services.

- `make docker-logs`
  Tail service logs.

- `make bootstrap`
  First-time Superset setup (run after `make docker-up`).

- `make cache-flush`
  Flush Superset/Redis cache (forces dashboards to re-query PostgreSQL).

- `make superset-export`
  Export Superset dashboards to `backups/` directory.

- `make superset-import`
  Import Superset dashboards from ZIP.
  Example:

  ```bash
  make superset-import FILE=backups/export.zip
  ```

## CI & Release

- `make ci-generate`
  Generate child pipeline YAML (`regular`, `dynamic`, `discover`).

- `make ci-report`
  Generate repo metrics. Add `POST_MR=1` to post to MR.

- `make ci-deploy`
  Deploy Superset to remote host.

- `make run-ci-pipeline`
  Run the full CI pipeline locally.
  Add `ROBOT=1` for live Robot tests.

- `make opencode-pipeline-review`
  Run OpenCode AI review in CI (pipeline failures + MR diff).

- `make opencode-local-review`
  Run OpenCode AI review on local uncommitted/branch changes.

- `make opencode-audit-markdown`
  Audit markdown file references for broken/stale paths (Ollama).

- `make ci-release`
  Build and verify PyPI package.
  Dry run by default; set `UPLOAD=1` to publish.

## Misc

- `make help`
  Show Makefile help.

- `make install`
  Install Python dependencies.

- `make version`
  Print current version.
