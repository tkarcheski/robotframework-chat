# Feature Tracker

Status of every major feature, ordered by priority.
Updated from code audit and git history as of 2026-02-15.

**Legend:** Done / In Progress / Not Started

---

## Priority 1 — Superset Database & Reporting (In Progress)

The Superset stack is functional but still in development. Core infrastructure
works; the gap is data quality, retention, and operational polish.

| Feature | Status | Notes |
|---------|--------|-------|
| PostgreSQL 16 + Redis 7 Docker stack | Done | `docker-compose.yml` with health checks |
| SQLite fallback (zero-config) | Done | `data/test_history.db` when `DATABASE_URL` unset |
| Dual-backend TestDatabase | Done | `src/rfc/test_database.py` — auto-selects by URL prefix |
| Auto-bootstrapped Superset dashboard | Done | `superset/bootstrap_dashboards.py` — 6 charts, 3 datasets |
| Pass Rate Over Time (line chart) | Done | Daily granularity |
| Model Comparison — Pass Rate (bar) | Done | |
| Test Results Breakdown (pie) | Done | |
| Test Suite Duration Trend (line) | Done | |
| Recent Test Runs (table) | Done | 50-row limit |
| Failures by Test Name (bar) | Done | |
| Remote deploy via CI | Done | `ci/deploy.sh` → `make ci-deploy` |
| CI pipeline artifact sync | Done | `scripts/sync_ci_results.py` + `ci/sync_db.sh` |
| `.env` configuration flow | Done | Makefile, CI scripts, pytest, suite_config all load `.env` |
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

## Principles

See [AGENTS.md — Core Philosophy](AGENTS.md#core-philosophy).

- Testing before training
- Automation before dashboards
- Regression detection over anecdotal evaluation
- AI systems should be testable, repeatable, and auditable
