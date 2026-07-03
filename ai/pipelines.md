# Pipeline Strategy

This document describes the CI/CD pipeline architecture and model selection
strategy for robotframework-chat.

> **Historical note:** the original pipeline ran on GitLab CI (per-node
> runner tags, child pipelines, MR comments). GitLab CI support was removed
> at source (rfc-monorepo #106/#107); GitHub Actions is the only CI.

---

## Architecture: Minimal YAML, Modular Logic

The CI pipeline follows a strict separation of concerns:

```
.github/workflows/       # Workflow YAML: triggers, jobs, artifacts
Makefile                 # Targets wrap all executable logic for local + CI use
config/test_suites.yaml  # Single source of truth for test suites
config/local_models.yaml # Local model discovery and test config
```

**Strong requirement:** workflow YAML stays minimal. To change pipeline
behavior, edit Makefile targets (or the scripts they wrap) — not the YAML.

### Design Principles

1. **Simple** — each workflow is readable at a glance
2. **Modular** — each job handles one concern (lint, test, publish, etc.)
3. **Reusable** — logic runs identically in CI and locally (`make ...`)
4. **Extendable** — add a Makefile target, add a job that calls it
5. **Fail fast and loud** — strict shell modes, verbose error diagnostics

---

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `robot-tests.yml` | Push / PR | Lint, pytest, Robot dry-run, robot tests |
| `docker-publish.yml` | See workflow | Build and publish the Docker image |
| `pypi-publish.yml` | Tag push (`v*`) | Build and publish package to PyPI |

### Per-node test strategy (removed)

The GitLab-era pipeline dispatched one `make run-local-models` job per fleet
node via GitLab runner tags. That mechanism was removed with GitLab CI
support (#106/#107). Per-node runs are now executed locally with
`make run-local-models` on each node.

---

## Local Verification

Run the CI checks locally before pushing:

| Check | Command | Notes |
|-------|---------|-------|
| install | `make install` | `uv sync` all extras |
| lint | `pre-commit run --all-files` | yaml, json, whitespace, ruff, mypy |
| lint | `make code-quality-check` | ruff + mypy + coverage |
| test | `uv run pytest` | Python unit tests |
| test | `make robot-dryrun` | validate robot test syntax |

---

## Listeners

Every Robot Framework run in CI attaches all three listeners:

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives results to SQL (SQLite or PostgreSQL) |
| `rfc.git_metadata_listener.GitMetaData` | Adds CI context (commit, branch, run URL) from GitHub Actions |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamps every Ollama chat call |

---

## Configuration

All test suite definitions live in `config/test_suites.yaml`. This single
file drives test configuration for local runs and CI. Changes propagate
automatically — no manual editing of workflow YAML for test jobs.

See [agents.md](agents.md) for the full project architecture.

---

## Model-to-Node Assignment (Planned)

> **Owner decision (2026-02-19):** Owner wants to control which models are
> loaded on which hosts. Tracked in the owner backlog (private monorepo)
> § Model-to-node assignment config.

Short-term: a `config/model_assignments.yaml` file.
Long-term: web UI to manage assignments.

---

## Branching Model

> **Owner decision (2026-02-19):**

- `main` — human-reviewed, tested, stable
- `claude-code-staging` — AI agent working branch (long-lived)
- `claude/*` — per-session feature branches -> PR into staging
- CI runs on both `main` and staging (regression detection)
- Owner syncs staging -> main after review and testing

---

## AI-Powered Code Review Stage (Planned)

> **Owner decision (2026-02-19):** The AI review stage should approve/deny PRs,
> grade code quality, and generate full reports.

Removed 2026-06-10 (CI/CD audit): PR review is handled by Codex (auto-assign) and the Claude heartbeat sweep.
Planned: AI agent reviews both code diff AND pipeline results, posts structured
report with pass/fail + letter grade.
