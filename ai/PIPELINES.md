# Pipeline Strategy

This document describes the pipeline architecture and model selection
strategy for robotframework-chat CI/CD.

---

## Architecture: Minimal YAML, Modular Scripts

The CI pipeline follows a strict separation of concerns:

```
.gitlab-ci.yml          # Skeleton: stages, rules, artifacts (~170 lines)
ci/common.yml           # Shared YAML templates (.uv-setup, .robot-test)
ci/*.sh                 # All executable logic (bash scripts)
Makefile                # ci-* targets wrap scripts for local + CI use
scripts/generate_pipeline.py  # Child-pipeline YAML from config/test_suites.yaml
config/test_suites.yaml       # Single source of truth for test suites
```

**Strong requirement:** `.gitlab-ci.yml` stays minimal. To change pipeline
behavior, edit `ci/*.sh` scripts or `Makefile` targets — not the YAML.

### Design Principles

1. **Simple** — the YAML skeleton is readable at a glance
2. **Modular** — each script handles one concern (lint, test, deploy, etc.)
3. **Reusable** — scripts run identically in CI and locally (`make ci-lint`)
4. **Extendable** — add a new script, add a job that calls it
5. **Fail fast and loud** — `set -euo pipefail`, verbose error diagnostics
6. **Dynamic** — child pipelines generated from config, not hardcoded YAML

---

## Pipeline Modes

There are three pipeline modes, all generated from
`config/test_suites.yaml` via `scripts/generate_pipeline.py`:

| Mode | Trigger | Purpose |
|------|---------|---------|
| **Regular** | Every push / MR | Smoke-test the system works with the smallest viable model |
| **Dynamic** | Manual play-button | Discover Ollama nodes on the network, enumerate models, run every (node, model, suite) combination |
| **Scheduled** | Hourly cron | Run the dynamic pipeline automatically for continuous coverage |

---

## Model Selection Strategy

### Regular pipeline: smallest viable model

The regular pipeline exists to verify that **the testing system itself works** —
not to evaluate model quality. For this reason it always runs on the smallest
model that can pass the test suites.

- **Current default:** `llama3` (set in `.gitlab-ci.yml` and `config/test_suites.yaml`)
- As test suites grow and require more capable responses, the default model
  is bumped to the **smallest model that satisfies all suites**
- The goal is fast feedback on code changes, not model benchmarking

### Dynamic and scheduled pipelines: test every model

The dynamic pipeline discovers all available Ollama nodes and their loaded
models, then runs every (node, model, suite) combination. This is where
actual model evaluation and comparison happens.

- Scheduled pipelines run hourly to catch model regressions over time
- Manual triggers let developers test specific models on demand
- Results are archived to SQL and visualized in Superset dashboards

### When to update the default model

Update `DEFAULT_MODEL` in `.gitlab-ci.yml` and `defaults.model` in
`config/test_suites.yaml` when:

1. A new test suite requires capabilities the current default lacks
2. The current default model is deprecated or unavailable
3. A smaller model becomes available that still passes all suites

Always pick the **smallest model that passes all regular-pipeline suites**.

---

## Pipeline Stages

```
lint → generate → test → report → deploy → review
```

| Stage | Job(s) | Script | Notes |
|-------|--------|--------|-------|
| `lint` | `lint` | `ci/lint.sh` | Runs pre-commit, ruff, mypy (allow_failure) |
| `generate` | `generate-regular-pipeline`, `discover-nodes`, `generate-dynamic-pipeline` | `ci/generate.sh` | Produce child-pipeline YAML from `test_suites.yaml` |
| `test` | `run-regular-tests`, `run-dynamic-tests` | (child pipelines) | Execute generated child pipelines |
| `report` | `repo-metrics` | `ci/report.sh` | Repo metrics, MR comments |
| `deploy` | `deploy-superset` | `ci/deploy.sh` | Update Superset stack on default branch |
| `review` | `opencode-review` | `ci/review.sh` | AI code review + fix via OpenCode + Kimi K2.5 on OpenRouter |

---

## CI Scripts Reference

| Script | Usage | Arguments |
|--------|-------|-----------|
| `ci/lint.sh` | `bash ci/lint.sh [all\|pre-commit\|ruff\|mypy]` | Check type (default: all) |
| `ci/test.sh` | `bash ci/test.sh [all\|math\|docker\|safety]` | Suite to run (default: all) |
| `ci/generate.sh` | `bash ci/generate.sh [regular\|dynamic\|discover]` | Pipeline mode |
| `ci/report.sh` | `bash ci/report.sh [--post-mr]` | Post metrics as MR comment |
| `ci/deploy.sh` | `bash ci/deploy.sh` | Requires SUPERSET_DEPLOY_* vars |
| `ci/review.sh` | `bash ci/review.sh` | Requires OPENROUTER_API_KEY |

All scripts can be invoked via Makefile targets: `make ci-lint`, `make ci-test`, etc.

---

## Listeners

Every Robot Framework run in CI attaches all three listeners:

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives results to SQL (SQLite or PostgreSQL) |
| `rfc.git_metadata_listener.GitMetaData` | Adds CI context (commit, branch, pipeline URL) from GitHub Actions or GitLab CI |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamps every Ollama chat call |

---

## Configuration

All test suite definitions live in `config/test_suites.yaml`. This single
file drives both the dashboard UI and CI pipeline generation. Changes
propagate automatically — no manual YAML editing in `.gitlab-ci.yml` for
test jobs.

See [AGENTS.md](AGENTS.md) for the full project architecture.

---

## Node Auto-Discovery (Planned)

> **Owner decision (2026-02-19):** Pipelines should discover which nodes are
> online before scheduling jobs. See `humans/TODO.md` § Pipeline node auto-discovery.

Proposed flow:
1. Ping each node's Ollama `/api/tags` endpoint
2. Build a live inventory of online nodes + available models
3. Schedule jobs only to reachable nodes

This replaces hardcoded node lists in `config/test_suites.yaml`.

---

## Model-to-Node Assignment (Planned)

> **Owner decision (2026-02-19):** Owner wants to control which models are
> loaded on which hosts. See `humans/TODO.md` § Model-to-node assignment config.

Short-term: a `config/model_assignments.yaml` file.
Long-term: web UI to manage assignments.

---

## Branching Model

> **Owner decision (2026-02-19):** See `ai/CLAUDE.md` § Branching Model.

- `main` — human-reviewed, tested, stable
- `claude-code-staging` — AI agent working branch (long-lived)
- `claude/*` — per-session feature branches -> PR into staging
- GitLab CI runs on both `main` and staging (regression detection)
- GitHub mirrors for code checks only
- Owner syncs staging -> main after review and testing

---

## AI-Powered Code Review Stage (Planned)

> **Owner decision (2026-02-19):** The AI review stage should approve/deny PRs,
> grade code quality, and generate full reports. See `humans/TODO.md` § AI-Powered
> Code Review in CI.

Current: `ci/review.sh` uses OpenCode + Kimi K2.5 via OpenRouter.
Planned: AI agent reviews both code diff AND pipeline results, posts structured
report with pass/fail + letter grade.
