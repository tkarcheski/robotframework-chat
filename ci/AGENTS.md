# CI Agent Inventory

> **Note:** The canonical documentation for CI/CD lives in `ai/pipelines.md`
> and `docs/requirements.md`. This file contains CI-specific script details that
> supplement those documents.

Scripts and automation agents used in the GitHub Actions CI pipeline.

## Pipeline Agents

| Script | Stage | Purpose |
|--------|-------|---------|
| `ci/lint.sh` | lint | Run ruff linter and formatter checks |
| `ci/deploy.sh` | deploy | Deploy Superset to remote host |
| `ci/release.sh` | release | Build + verify sdist/wheel (`make build-check`) |
| `ci/backup_push.sh` | manual | Push Superset export + DB dump to the backups repo |
| `ci/audit_markdown.sh` | manual | Audit markdown file references (Ollama) |

Removed by the 2026-06-14 GitHub-only migration (RFC-001 Phase 4):
`ci/report.sh`, `ci/pipeline_report.sh`, `ci/common.yml`,
`scripts/pipeline_summary.py`, `scripts/ci-diagnostics.sh`, and
`scripts/build-ci-image.sh`.

## Listener Agents

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Write test results to database |
| `rfc.git_metadata_listener.GitMetaData` | Attach git commit/branch metadata to results |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamp Ollama API calls during tests |

## Pipeline Simplicity

Keep CI pipelines minimal. Debugging workflow YAML is painful, so prefer
pushing logic into developer tools that work the same locally and in CI:

- **Makefile** — entry points for CI operations (`make ci-deploy`,
  `make code-quality-check`, etc.). A developer should be able to
  reproduce any CI job locally.
- **Bash scripts** (`ci/*.sh`) — reusable scripts that set up the
  environment and call Python or other tools. Some are called directly
  from GitHub Actions workflows (e.g. `bash ci/lint.sh all`). Keep them
  short and linear.
- **Python scripts** (`scripts/`) — for anything that needs real logic
  (discovery, result import, report generation). These are testable and
  debuggable outside CI.

The workflow YAML should do as little as possible: pick a runner, call a
script, collect artifacts. Avoid CI-specific features that cannot be
exercised locally.
