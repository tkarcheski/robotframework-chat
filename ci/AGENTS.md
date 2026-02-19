# CI Agent Inventory

> **Note:** The canonical documentation for CI/CD lives in `ai/PIPELINES.md`
> and `ai/FEATURES.md`. This file contains CI-specific script details that
> supplement those documents.

Scripts and automation agents used in the GitLab CI pipeline.

## Pipeline Agents

| Script | Stage | Purpose |
|--------|-------|---------|
| `ci/lint.sh` | lint | Run ruff linter and formatter checks |
| `ci/test.sh` | test | Run Robot Framework test suites with health checks |
| `ci/generate.sh` | generate | Generate child pipeline YAML for dynamic jobs |
| `ci/report.sh` | report | Generate repo metrics and optionally post to MR |
| `ci/sync.sh` | sync | Mirror repository to GitHub |
| `ci/sync_db.sh` | sync | Import CI pipeline test artifacts to database |
| `ci/deploy.sh` | deploy | Deploy Superset to remote host |
| `ci/test_dashboard.sh` | test | Run dashboard pytest and Playwright tests |
| `ci/review.sh` | review | Run AI code review on pipeline changes |
| `ci/ensure_node.sh` | setup | Ensure Node.js >= 18 is available |

## Sync Agent

`scripts/sync_ci_results.py` is the primary CI artifact sync agent. It:

1. Connects to the GitLab API to list recent successful pipelines
2. Fetches job lists for each pipeline
3. Downloads `output.xml` artifacts from each job
4. Imports results into the test database via `import_test_results.py`
5. Deduplicates using the `pipeline_url` column in `test_runs`

### Environment Resolution

Settings are resolved in priority order:

1. Explicit constructor parameters (for testing)
2. `CI_API_V4_URL` / `CI_PROJECT_ID` (inside GitLab CI runners)
3. `GITLAB_API_URL` / `GITLAB_PROJECT_ID` environment variables

The `.env` file is loaded by `ci/sync_db.sh` and the Makefile before invoking the sync script.

## Listener Agents

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Write test results to database |
| `rfc.git_metadata_listener.GitMetaData` | Attach git commit/branch metadata to results |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamp Ollama API calls during tests |

## Pipeline Simplicity

Keep CI pipelines minimal. GitLab CI has hard limits (e.g. a job can
only `needs` 50 others) and debugging generated YAML is painful. Prefer
pushing logic into developer tools that work the same locally and in CI:

- **Makefile** — entry points for every CI operation (`make ci-lint`,
  `make ci-test`, etc.). A developer should be able to reproduce any CI
  job by running the corresponding `make` target.
- **Bash scripts** (`ci/*.sh`) — thin wrappers that set up the
  environment and call Python or other tools. Keep them short and
  linear.
- **Python scripts** (`scripts/`) — for anything that needs real logic
  (discovery, result import, report generation). These are testable and
  debuggable outside CI.

The `.gitlab-ci.yml` and generated child pipelines should do as little
as possible: pick a runner, call a script, collect artifacts. Avoid
`needs` chains, multi-stage fan-in/fan-out, and any CI-specific feature
that cannot be exercised locally.
