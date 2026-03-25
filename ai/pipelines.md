# Pipeline Strategy

This document describes the pipeline architecture and model selection
strategy for robotframework-chat CI/CD.

---

## Architecture: Minimal YAML, Modular Scripts

The CI pipeline follows a strict separation of concerns:

```
.gitlab-ci.yml          # Skeleton: stages, rules, artifacts (~165 lines)
ci/common.yml           # Shared YAML templates (.uv-setup, .robot-test)
ci/*.sh                 # All executable logic (bash scripts)
Makefile                # ci-* targets wrap scripts for local + CI use
config/test_suites.yaml # Single source of truth for test suites
config/local_models.yaml # Local model discovery and test config
```

**Strong requirement:** `.gitlab-ci.yml` stays minimal. To change pipeline
behavior, edit `ci/*.sh` scripts or `Makefile` targets — not the YAML.

### Design Principles

1. **Simple** — the YAML skeleton is readable at a glance
2. **Modular** — each script handles one concern (lint, test, deploy, etc.)
3. **Reusable** — scripts run identically in CI and locally (`make ci-lint`)
4. **Extendable** — add a new script, add a job that calls it
5. **Fail fast and loud** — `set -euo pipefail`, verbose error diagnostics
6. **Per-node** — each runner tag gets its own job, `allow_failure: true`

---

## Pipeline Modes

| Mode | Trigger | Purpose |
|------|---------|---------|
| **Test** | Every push / MR | Per-node `make run-local-models` on ai1, mini1, mini2, dev1, dev2 |
| **Release** | Tag push (`v*`) | Build and publish package to PyPI |
| **Test Release** | Pre-release tag (`v*-rc*`) | Build and verify only |

### Per-node test strategy

Each node gets its own CI job, dispatched by GitLab runner tag. Every job
runs `make run-local-models`, which discovers models on the local Ollama
instance and runs all test suites against each model.

- All per-node jobs have `allow_failure: true` — nodes may be offline
- Jobs wait for `lint` to pass before starting
- Results are archived to `results/` and collected as artifacts
- Node list: `ai1`, `mini1`, `mini2`, `dev1`, `dev2`

---

## Local CI Pipeline

Run the full CI pipeline locally with a single command:

```bash
make run-ci-pipeline                      # lint + dashboard tests + robot dryrun + release verify
make run-ci-pipeline ROBOT=1              # same, plus live robot tests (requires Ollama)
make run-ci-pipeline ROBOT=1 SUITE=math   # live tests, math suite only
```

Stages run locally:

| Stage | Command | Notes |
|-------|---------|-------|
| install | `make install` | `uv sync` all extras |
| lint | `make ci-lint` | pre-commit + ruff + mypy |
| test | `make ci-test-dashboard MODE=pytest` | dashboard unit tests |
| test | `make robot-dryrun` | validate robot test syntax |
| test | `make ci-test` | live robot tests (only with `ROBOT=1`) |
| release | `make ci-release` | dry-run package build + twine verify |

Stages skipped locally (CI-only):

| Stage | Why |
|-------|-----|
| report | MR comments via GitLab API |
| deploy | remote host deployment |
| review | AI code review (requires opencode-ai + OpenRouter) |

---

## Pipeline Stages

```
lint → test → report → deploy → release → review
```

| Stage | Job(s) | Make target | Notes |
|-------|--------|-------------|-------|
| `lint` | `lint` | `make ci-lint` | Runs pre-commit, ruff, mypy |
| `test` | `run-local-models-{ai1,mini1,mini2,dev1,dev2}` | `make run-local-models` | Per-node model discovery + test runs (`allow_failure`) |
| `report` | `repo-metrics`, `pipeline-summary` | `make ci-report`, `make ci-pipeline-report` | Repo metrics, MR comments |
| `deploy` | `deploy-superset` | `make ci-deploy` | Update Superset stack on default branch |
| `release` | `test-release`, `publish-pypi` | `make ci-release [UPLOAD=1]` | Build + publish to PyPI on version tags (`v*`) |
| `review` | `opencode-review` | `make opencode-pipeline-review` | AI code review + fix via OpenCode + Kimi K2.5 on OpenRouter |

---

## CI Scripts Reference

| Script | Usage | Arguments |
|--------|-------|-----------|
| `ci/lint.sh` | `bash ci/lint.sh [all\|pre-commit\|ruff\|mypy]` | Check type (default: all) |
| `ci/test.sh` | `bash ci/test.sh [all\|math\|docker\|safety]` | Suite to run (default: all) |
| `ci/generate.sh` | `bash ci/generate.sh [regular\|dynamic\|discover]` | Pipeline mode |
| `ci/report.sh` | `bash ci/report.sh [--post-mr]` | Post metrics as MR comment |
| `ci/deploy.sh` | `bash ci/deploy.sh` | Requires SUPERSET_DEPLOY_* vars |
| `ci/release.sh` | `bash ci/release.sh [--dry-run]` | Requires PYPI_TOKEN or TWINE_USERNAME+PASSWORD |
| `ci/review.sh` | `bash ci/review.sh` | Requires OPENROUTER_API_KEY |

All scripts can be invoked via Makefile targets: `make ci-lint`, `make ci-test`,
`make ci-release`, etc.

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

See [agents.md](agents.md) for the full project architecture.

---

## Node Strategy

Each physical node has a GitLab runner with a matching tag (`ai1`, `mini1`,
`mini2`, `dev1`, `dev2`). The CI pipeline creates one job per node. Each job
runs `make run-local-models`, which discovers models on the local Ollama
instance automatically via `scripts/run_local_models.py`.

Nodes that are offline simply have their job stay pending or fail — this is
safe because all per-node jobs have `allow_failure: true`.

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
