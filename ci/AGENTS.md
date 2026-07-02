# CI Agent Inventory

> **Note:** The canonical documentation for CI/CD lives in `ai/pipelines.md`
> and `docs/requirements.md`. This file contains CI-specific script details that
> supplement those documents.

Scripts and automation agents used in the GitLab CI pipeline.

## Pipeline Agents

| Script | Stage | Purpose |
|--------|-------|---------|
| `ci/lint.sh` | lint | Run ruff linter and formatter checks |
| `ci/report.sh` | report | Repo metrics, optional MR post (manual: `make ci-report`) |
| `ci/pipeline_report.sh` | report | Pipeline summary, posts to MR |
| `ci/deploy.sh` | deploy | Deploy Superset to remote host |
| `ci/release.sh` | release | Build + verify sdist/wheel (`make build-check`) |
| `ci/backup_push.sh` | manual | Push Superset export + DB dump to the backups repo |
| `ci/audit_markdown.sh` | manual | Audit markdown file references (Ollama) |

Removed by the 2026-06-10 CI/CD audit (elons-algorithm report
`2026-06-10-cicd-pipelines.md`): `ci/test.sh`, `ci/sync.sh`,
`ci/ensure_node.sh`, `ci/send_results.sh`, `ci/generate.sh` +
`scripts/generate_pipeline.py`, `ci/review.sh`, `ci/local_review.sh`.

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

- **Makefile** — entry points for CI operations (`make ci-report`,
  `make ci-deploy`, etc.). A developer should be able to reproduce any
  CI job locally.
- **Bash scripts** (`ci/*.sh`) — reusable scripts that set up the
  environment and call Python or other tools. Some are called directly
  from `.gitlab-ci.yml` (e.g. `bash ci/lint.sh all`). Keep them short
  and linear.
- **Python scripts** (`scripts/`) — for anything that needs real logic
  (discovery, result import, report generation). These are testable and
  debuggable outside CI.

The `.gitlab-ci.yml` should do as little
as possible: pick a runner, call a script, collect artifacts. Avoid
`needs` chains, multi-stage fan-in/fan-out, and any CI-specific feature
that cannot be exercised locally.
