# Feature Tracker

Status of every major feature, ordered by priority.
Updated from code audit and git history as of 2026-02-17.
Updated listener review as of 2026-02-15.
Updated Superset dashboard and Makefile completeness as of 2026-02-17.

**Legend:** Done / In Progress / Not Started

---

## Priority 1 — Superset Database & Reporting (In Progress)

The Superset stack is partially functional. The **charts view** is working
(all 6 charts render correctly) and **Recent Test Runs** table displays
data. The remaining dashboard features (cross-filtering, alerts, per-model
dashboards, retention, scheduled exports) are not yet complete.

| Feature | Status | Notes |
|---------|--------|-------|
| PostgreSQL 16 + Redis 7 Docker stack | Done | `docker-compose.yml` with health checks |
| SQLite fallback (zero-config) | Done | `data/test_history.db` when `DATABASE_URL` unset |
| Dual-backend TestDatabase | Done | `src/rfc/test_database.py` — auto-selects by URL prefix |
| Auto-bootstrapped Superset dashboard | Done | `superset/bootstrap_dashboards.py` — 6 charts, 3 datasets |
| Pass Rate Over Time (line chart) | Done | Verified working in charts view |
| Model Comparison — Pass Rate (bar) | Done | Verified working in charts view |
| Test Results Breakdown (pie) | Done | Verified working in charts view |
| Test Suite Duration Trend (line) | Done | Verified working in charts view |
| Recent Test Runs (table) | Done | 50-row limit, verified working |
| Failures by Test Name (bar) | Done | Verified working in charts view |
| Remote deploy via CI | Done | `ci/deploy.sh` → `make ci-deploy` |
| CI pipeline artifact sync | Done | `scripts/sync_ci_results.py` + `ci/sync_db.sh` |
| `.env` configuration flow | Done | Makefile, CI scripts, pytest, suite_config all load `.env` |
| Full dashboard layout & navigation | In Progress | Charts view works; overall dashboard needs polish |
| Cross-filtering and drill-down | Not Started | Superset native capabilities, needs chart updates |
| Model regression alerts | Not Started | Threshold-based notifications on pass-rate drops |
| Per-model trend dashboards | Not Started | Auto-generated per discovered model |
| Data retention policies | Not Started | Automatic cleanup of old test runs |
| Scheduled dashboard refresh/export | Not Started | Periodic snapshot or PDF generation |

### What to work on next

1. **Data retention** — define a policy (e.g. keep 90 days) and add a cleanup
   script or cron job so the database doesn't grow unbounded.
2. **Cross-filtering** — enable drill-down by model, suite, and branch in
   Superset charts so users can investigate regressions interactively.
3. **Regression alerts** — flag when a model's pass rate drops below a
   configurable threshold (could be a CI job or Superset alert).

---

## Listener Infrastructure (Done)

Three Robot Framework listeners handle test result collection. All three
have been reviewed, bugs fixed, and comprehensive unit tests added.

| Feature | Status | Notes |
|---------|--------|-------|
| DbListener — SQL archival | Done | `src/rfc/db_listener.py` — archives runs + results to SQLite/PostgreSQL |
| GitMetaData — CI metadata | Done | `src/rfc/git_metadata_listener.py` — collects CI context, formats links |
| OllamaTimestampListener — chat timing | Done | `src/rfc/ollama_timestamp_listener.py` — timestamps Ollama keyword calls |
| DbListener unit tests | Done | `tests/test_db_listener.py` — 27 tests |
| GitMetaData unit tests | Done | `tests/test_git_metadata_listener.py` — 26 tests |
| OllamaTimestampListener unit tests | Done | `tests/test_ollama_timestamp_listener.py` — 22 tests |
| GitMetaData suite depth tracking | Done | Fixed: metadata collection and JSON save restricted to top-level suite |
| OllamaTimestampListener keyword verification | Done | Fixed: `end_keyword` verifies keyword name matches before recording |
| git_metadata module unit tests | Done | `tests/test_git_metadata.py` — 10 tests |
| TestDatabase unit tests | Done | `tests/test_test_database.py` — 13 tests |

---

## Priority 2 — Dashboard Control Panel (Functional)

The Dash-based UI is feature-rich and production-grade. Remaining work is
incremental polish.

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-session management (5 tabs) | Done | `dashboard/core/session_manager.py` |
| Test runner with live output | Done | `dashboard/core/robot_runner.py` |
| Auto-recovery on failure | Done | 3 max attempts, configurable delay |
| Session controls (run/stop/replay/delete) | Done | |
| Suite/IQ/model/profile dropdowns | Done | Populated from `config/test_suites.yaml` |
| Result upload to database | Done | Export button per session |
| Ollama Hosts monitoring tab | Done | Polls `/api/tags` + `/api/ps`, 24hr ring buffer |
| GitLab Pipelines monitoring tab | Done | Real-time pipeline status table |
| Git remote auto-detection | Done | SSH + HTTPS GitLab remotes |
| Docker-aware node rewriting | Done | `localhost` → `host.docker.internal` in bridge mode |
| Dark theme | Done | Consistent across all tabs |
| Playwright browser tests | Done | `robot/dashboard/tests/` |

---

## Priority 3 — Structured Evaluation (In Progress)

Binary pass/fail grading is solid. Multi-score rubrics are the main gap
blocking richer evaluation workflows.

| Feature | Status | Notes |
|---------|--------|-------|
| Binary grading (0/1) | Done | `GradeResult` enforces `score in (0, 1)` |
| JSON-only grader contracts | Done | Strict structured output |
| Safety grading with confidence | Done | `SafetyGrader` returns 0.0–1.0 confidence |
| Safety keywords (11 keywords) | Done | `src/rfc/safety_keywords.py` |
| Safety test suites (4 .robot files) | Done | Injection, extraction, jailbreak, indirect |
| Multi-score rubrics (0–5) | Not Started | Requires `GradeResult` redesign |
| Partial credit support | Not Started | Requires grader prompt + schema changes |
| Tolerance rules (numeric ranges) | Not Started | Equivalence matching for math answers |
| Canonical answer normalization | Not Started | Strip whitespace, units, formatting |

### What to work on next

1. **Multi-score rubrics** — extend `GradeResult` to support 0–5 scores with
   categorical dimensions (accuracy, clarity, reasoning). Update grader prompt,
   database schema (`score` column → allow range), and test assertions.
2. **Tolerance rules** — add numeric range matching so `3.14` and `3.1416` can
   both pass. Useful for math test suites.

---

## Priority 4 — Docker & Container Testing (Done)

Fully implemented with 3 test suites and resource-constrained execution.

| Feature | Status | Notes |
|---------|--------|-------|
| Container manager | Done | `src/rfc/container_manager.py` |
| Docker keywords (7 keywords) | Done | `src/rfc/docker_keywords.py` |
| Container profiles (MINIMAL/STANDARD/PERFORMANCE) | Done | `config/test_suites.yaml` |
| Python code execution tests | Done | `robot/docker/python/tests/` |
| Shell command execution tests | Done | `robot/docker/shell/tests/` |
| Multi-model LLM-in-Docker tests | Done | `robot/docker/llm/tests/` |
| Dynamic port allocation | Done | `Find Available Port` keyword |
| Resource limits (CPU/memory/disk) | Done | Configurable per-container |

---

## Priority 5 — CI/CD Pipeline (Done)

Seven-stage GitLab pipeline with modular scripts.

| Feature | Status | Notes |
|---------|--------|-------|
| Modular CI scripts (`ci/*.sh`) | Done | 8 scripts, all `set -euo pipefail` |
| Dynamic pipeline generation | Done | `scripts/generate_pipeline.py` from YAML config |
| Ollama network discovery | Done | `scripts/discover_nodes.py` |
| GitHub mirror sync | Done | `ci/sync.sh` |
| Claude Code review stage | Done | `ci/review.sh` — MR review + fix attempts |
| Repo metrics + MR comments | Done | `ci/report.sh` |
| `.env` sourcing in CI scripts | Done | `ci/sync_db.sh` sources `.env` |
| Single-source config | Done | `config/test_suites.yaml` drives dashboard + CI |
| Env var → YAML overlays | Done | `suite_config.py` applies `DEFAULT_MODEL`, `OLLAMA_ENDPOINT`, etc. |

---

## Priority 6 — LLM Manager (Not Started)

Multi-model orchestration for side-by-side comparison testing.

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-model configuration | Not Started | Single config for N endpoints |
| Parallel prompt execution | Not Started | Same prompt → multiple models concurrently |
| Response comparison | Not Started | Side-by-side grading |
| Model routing by capability | Not Started | Tag-based selection (e.g. `coding` → codellama) |
| Fallback chains | Not Started | Auto-failover when model unavailable |
| `Ask Multiple LLMs` keyword | Not Started | New Robot Framework keyword |

---

## Future — Multimodal Testing

Image + text, audio + text prompt support. Not prioritized until structured
evaluation (Priority 3) is complete.

| Feature | Status |
|---------|--------|
| Image + text prompts | Not Started |
| Audio + text prompts (ASR/TTS) | Not Started |
| Multimodal grading | Not Started |
| Artifact versioning and replay | Not Started |

---

## Future — MCP & Multi-Agent Testing

Test coordinated AI systems, not just single models. Depends on LLM Manager.

| Feature | Status |
|---------|--------|
| MCP integration | Not Started |
| Multi-model chat orchestration | Not Started |
| Agent-to-agent communication | Not Started |
| Task execution framework | Not Started |

---

## Future — A/B Evaluation Pipelines

Measure the impact of model changes scientifically. Depends on multi-score
rubrics and the LLM Manager.

| Feature | Status |
|---------|--------|
| A/B testing framework | Not Started |
| Prompt vs model comparison | Not Started |
| Dataset replay | Not Started |
| Statistical comparison | Not Started |
| Regression gating in CI | Not Started |

---

## Makefile Command Completeness

Status of every `make` target. **Working** means the command runs
successfully end-to-end in a properly configured environment.

| Command | Status | Category | Notes |
|---------|--------|----------|-------|
| `make help` | Working | Setup | Lists all targets with descriptions |
| `make install` | Working | Setup | `uv sync --extra dev --extra dashboard --extra superset` |
| `make docker-up` | Working | Docker | Starts PostgreSQL + Redis + Superset + Dashboard |
| `make docker-down` | Not Complete | Docker | Depends on running stack; untested in isolation |
| `make docker-restart` | Not Complete | Docker | Depends on running stack |
| `make docker-logs` | Not Complete | Docker | Depends on running stack |
| `make bootstrap` | Working | Docker | First-time Superset setup after `docker-up` |
| `make robot` | Working | Robot Tests | Runs all suites (math + docker + safety) |
| `make robot-math` | Not Complete | Robot Tests | Requires Ollama endpoint |
| `make robot-docker` | Not Complete | Robot Tests | Requires Docker daemon |
| `make robot-safety` | Not Complete | Robot Tests | Requires Ollama endpoint |
| `make robot-dryrun` | Not Complete | Robot Tests | Validates .robot files without execution |
| `make test-dashboard` | Not Complete | Dashboard | Runs dashboard pytest unit tests |
| `make test-dashboard-playwright` | Not Complete | Dashboard | Browser self-tests, requires Playwright |
| `make import` | Working | Data | Imports output.xml results into database |
| `make code-lint` | Working | Code Quality | Runs ruff linter (`make code` shorthand) |
| `make code-format` | Not Complete | Code Quality | Auto-formats with ruff |
| `make code-typecheck` | Not Complete | Code Quality | Runs mypy on `src/` |
| `make code-check` | Not Complete | Code Quality | Runs lint + typecheck together |
| `make ci-lint` | Not Complete | CI | CI lint wrapper |
| `make ci-test` | Not Complete | CI | CI test wrapper with health checks |
| `make ci-generate` | Not Complete | CI | Generates child pipeline YAML |
| `make ci-report` | Not Complete | CI | Repo metrics + optional MR comment |
| `make ci-deploy` | Not Complete | CI | Deploys Superset to remote host |
| `make ci-test-dashboard` | Not Complete | CI | Dashboard tests in CI mode |
| `make opencode-pipeline-review` | Not Complete | AI Review | OpenCode AI review in CI |
| `make opencode-local-review` | Not Complete | AI Review | OpenCode AI review on local changes |
| `make ci-sync` | Not Complete | GitLab Sync | Mirror repo to GitHub |
| `make ci-status` | Not Complete | GitLab Sync | Check GitLab API connectivity |
| `make ci-list-pipelines` | Not Complete | GitLab Sync | List recent CI pipelines |
| `make ci-list-jobs` | Not Complete | GitLab Sync | List jobs in a pipeline |
| `make ci-fetch-artifact` | Not Complete | GitLab Sync | Download a single job artifact |
| `make ci-sync-db` | Not Complete | GitLab Sync | Sync CI pipeline results to database |
| `make ci-verify-db` | Not Complete | GitLab Sync | Verify database contents after sync |
| `make ci-list-pipeline-results` | Working | GitLab Sync | Lists pipeline_results from database |
| `make ci-backfill` | Deprecated | GitLab Sync | Replaced by `ci-sync-db` |
| `make ci-backfill-metadata` | Deprecated | GitLab Sync | Replaced by `ci-sync-db` |
| `make version` | Working | Versioning | Prints current version (fixed: uses `uv run python`) |
| `make code-coverage` | Working | Code Quality | Runs pytest with coverage report (new) |
| `make code-audit` | Working | Code Quality | Audits dependencies for vulnerabilities (new) |

### Summary

- **Working (11):** `help`, `install`, `docker-up`, `bootstrap`, `robot`,
  `import`, `code-lint`, `ci-list-pipeline-results`, `version`,
  `code-coverage`, `code-audit`
- **Not Complete (24):** Remaining targets need environment setup, testing,
  or implementation work
- **Deprecated (2):** `ci-backfill`, `ci-backfill-metadata`

---

## Principles

See [AGENTS.md — Core Philosophy](AGENTS.md#core-philosophy).

- Testing before training
- Automation before dashboards
- Regression detection over anecdotal evaluation
- AI systems should be testable, repeatable, and auditable
