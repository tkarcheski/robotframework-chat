# Pipeline Strategy

This document describes the CI pipeline architecture and model selection
strategy for robotframework-chat. CI runs on **GitHub Actions**.

---

## Architecture: Minimal YAML, Modular Scripts

The CI pipeline follows a strict separation of concerns:

```
.github/workflows/      # GitHub Actions workflow definitions
ci/*.sh                 # Executable logic (bash scripts), reusable locally + in CI
Makefile                # Targets wrap scripts for local + CI use
config/test_suites.yaml # Single source of truth for test suites
config/local_models.yaml # Local model discovery and test config
```

**Strong requirement:** workflow YAML stays minimal. To change pipeline
behavior, edit `ci/*.sh` scripts or `Makefile` targets — not the YAML.

### Design Principles

1. **Simple** — the YAML is readable at a glance
2. **Modular** — each script handles one concern (lint, release, deploy, etc.)
3. **Reusable** — scripts run identically in CI and locally
4. **Extendable** — add a new script, add a step that calls it
5. **Fail fast and loud** — `set -euo pipefail`, verbose error diagnostics

---

## GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `robot-tests.yml` | Push / PR | Lint, dashboard unit tests, robot dry-run |
| `pypi-publish.yml` | Tag push (`v*`) | Build and publish package to PyPI |
| `docker-publish.yml` | Tag / release | Build and publish container images |
| `auto-assign.yml` | PR opened | Reviewer auto-assignment |
| `claude-checkpoints.yml` | Scheduled / manual | Agent checkpoint sweeps |

---

## Local Verification

Run the core checks locally before pushing:

| Check | Command | Notes |
|-------|---------|-------|
| install | `make install` | `uv sync` all extras |
| lint | `make code-quality-check` | pre-commit + ruff + mypy |
| test | `uv run pytest` | Python unit tests |
| robot | `make robot-dryrun` | validate robot test syntax |
| release | `bash ci/release.sh --dry-run` | package build + twine verify |

---

## CI Scripts Reference

| Script | Usage | Arguments |
|--------|-------|-----------|
| `ci/lint.sh` | `bash ci/lint.sh [all\|pre-commit\|ruff\|mypy]` | Check type (default: all) |
| `ci/deploy.sh` | `bash ci/deploy.sh` | Requires SUPERSET_DEPLOY_* vars |
| `ci/release.sh` | `bash ci/release.sh [--dry-run]` | Requires PYPI_TOKEN or TWINE_USERNAME+PASSWORD |
| `ci/audit_markdown.sh` | `bash ci/audit_markdown.sh` | Audits markdown references |
| `ci/backup_push.sh` | `bash ci/backup_push.sh` | Backup helper |

---

## Listeners

Every Robot Framework run in CI attaches the core listeners:

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives results to SQL (SQLite or PostgreSQL) |
| `rfc.git_metadata_listener.GitMetaData` | Adds CI context (commit, branch, job URL) from GitHub Actions |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamps every Ollama chat call |

---

## Configuration

All test suite definitions live in `config/test_suites.yaml`. This single
file drives the dashboard UI and runner configuration.

See [agents.md](agents.md) for the full project architecture.

---

## Node Strategy

Each physical node runs a local Ollama instance. `make run-local-models`
discovers models on the local instance automatically via
`scripts/run_local_models.py` and runs all test suites against each model.
Node list: `ai1`, `mini1`, `mini2`, `dev1`, `dev2`.

---

## Model-to-Node Assignment (Planned)

> **Owner decision (2026-02-19):** Owner wants to control which models are
> loaded on which hosts. See `humans/TODO.md` § Model-to-node assignment config.

Short-term: a `config/model_assignments.yaml` file.
Long-term: web UI to manage assignments.

---

## Branching Model

> **Owner decision (2026-02-19):**

- `main` — human-reviewed, tested, stable
- `claude-code-staging` — AI agent working branch (long-lived)
- `claude/*` — per-session feature branches -> PR into staging
- GitHub Actions runs on both `main` and staging (regression detection)
- Owner syncs staging -> main after review and testing

---

## AI-Powered Code Review Stage (Planned)

> **Owner decision (2026-02-19):** The AI review stage should approve/deny PRs,
> grade code quality, and generate full reports. See `humans/TODO.md` § AI-Powered
> Code Review in CI.

Removed 2026-06-10 (CI/CD audit): PR review is handled by Codex (auto-assign) and the Claude heartbeat sweep.
Planned: AI agent reviews both code diff AND pipeline results, posts structured
report with pass/fail + letter grade.
