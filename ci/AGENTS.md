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
| `ci/deploy.sh` | deploy | Deploy Superset to remote host |
| `ci/test_dashboard.sh` | test | Run dashboard pytest and Playwright tests |
| `ci/review.sh` | review | Run AI code review on pipeline changes |
| `ci/ensure_node.sh` | setup | Ensure Node.js >= 18 is available |

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

- **Makefile** — entry points for CI operations (`make ci-generate`,
  `make ci-report`, etc.). A developer should be able to reproduce any
  CI job locally.
- **Bash scripts** (`ci/*.sh`) — reusable scripts that set up the
  environment and call Python or other tools. Some are called directly
  from `.gitlab-ci.yml` (e.g. `bash ci/lint.sh all`). Keep them short
  and linear.
- **Python scripts** (`scripts/`) — for anything that needs real logic
  (discovery, result import, report generation). These are testable and
  debuggable outside CI.

The `.gitlab-ci.yml` and generated child pipelines should do as little
as possible: pick a runner, call a script, collect artifacts. Avoid
`needs` chains, multi-stage fan-in/fan-out, and any CI-specific feature
that cannot be exercised locally.
