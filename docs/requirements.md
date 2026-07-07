# Project Requirements

Single source of truth for all project requirements and their current status.

Migrated from `ai/FEATURES.md` on 2026-03-04.

> **Cross-references:** See `ai/testing.md` for grading tiers and test rules.
> See the owner backlog (`modules/ops/humans/TODO.md`, private monorepo) for owner action items.

## Status Definitions

| Status | Symbol | Meaning |
|--------|--------|---------|
| **Complete** | :white_check_mark: | Implemented, tested, and working |
| **Functional** | :large_orange_diamond: | Partially implemented; core capability works but gaps remain |
| **Planned** | :white_circle: | Designed or specified but not yet implemented |
| **Deprecated** | :no_entry_sign: | Superseded; no further investment |

---

## 1. Database & Reporting

The data persistence layer for test results, model metadata, and analytics.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 1.1 | PostgreSQL 16 + Redis 7 Docker stack | Complete | `docker-compose.yml` with health checks |
| 1.2 | SQLite fallback (zero-config local) | Complete | `data/test_history.db` when `DATABASE_URL` unset |
| 1.3 | Dual-backend TestDatabase | Complete | `src/rfc/test_database.py` — auto-selects by URL prefix |
| 1.4 | `.env` configuration flow | Complete | Makefile, CI scripts, pytest, suite_config all load `.env` |
| 1.5 | Result import from `output.xml` | Complete | `make import PATH=results/` |
| 1.6 | Model metadata via `/api/show` | Planned | Quantization, architecture, context length, license |
| 1.7 | Performance metrics (tokens/sec) | Planned | `eval_count`, `eval_duration` from Ollama responses |
| 1.8 | Hardware context per test run | Planned | Node, GPU/TPU, VRAM recorded per run |
| 1.9 | Inference parameter storage | Planned | `temperature`, `seed`, `top_p`, `top_k` per run |
| 1.10 | Model size in GB + SHA256 digest | Planned | Enables "best model that fits in X GB VRAM" |
| 1.11 | Cost tracking (seconds / dollars) | Planned | Local = wall-clock seconds; cloud = dollars |
| 1.12 | 90-day rolling data retention | Planned | Archive older data to compressed exports |
| 1.13 | Suite version tracking | Planned | Git SHA of `.robot` file alongside results |

---

## 2. Visualization (Superset)

Apache Superset dashboards for test result analytics.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 2.1 | Auto-bootstrapped Superset dashboard | Complete | `superset/bootstrap_dashboards.py` — 6 charts, 3 datasets |
| 2.2 | Pass Rate Over Time (line chart) | Complete | Verified working |
| 2.3 | Model Comparison — Pass Rate (bar) | Complete | Verified working |
| 2.4 | Test Results Breakdown (pie) | Complete | Verified working |
| 2.5 | Test Suite Duration Trend (line) | Complete | Verified working |
| 2.6 | Recent Test Runs (table) | Complete | 50-row limit, verified working |
| 2.7 | Failures by Test Name (bar) | Complete | Verified working |
| 2.8 | Remote deploy via CI | Complete | `ci/deploy.sh` → `make ci-deploy` |
| 2.9 | Full dashboard layout & navigation | Functional | Charts view works; overall dashboard needs polish |
| 2.10 | Cross-filtering and drill-down | Planned | Superset native capabilities, needs chart updates |
| 2.11 | Model regression alerts | Planned | Threshold-based notifications on pass-rate drops |
| 2.12 | Per-model trend dashboards | Planned | Auto-generated per discovered model |
| 2.13 | Scheduled dashboard refresh/export | Planned | Periodic snapshot or PDF generation |

---

## 3. Listener Infrastructure

Robot Framework listeners for test result collection and metadata.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 3.1 | DbListener — SQL archival | Complete | `src/rfc/db_listener.py` — SQLite/PostgreSQL |
| 3.2 | GitMetaData — CI metadata | Complete | `src/rfc/git_metadata_listener.py` — CI context, links |
| 3.3 | OllamaTimestampListener — chat timing | Complete | `src/rfc/ollama_timestamp_listener.py` |
| 3.4 | DbListener unit tests (27 tests) | Complete | `tests/test_db_listener.py` |
| 3.5 | GitMetaData unit tests (26 tests) | Complete | `tests/test_git_metadata_listener.py` |
| 3.6 | OllamaTimestampListener unit tests (22 tests) | Complete | `tests/test_ollama_timestamp_listener.py` |
| 3.7 | Suite depth tracking (GitMetaData) | Complete | Metadata restricted to top-level suite |
| 3.8 | Keyword verification (Timestamp) | Complete | `end_keyword` verifies name before recording |
| 3.9 | git_metadata module tests (10 tests) | Complete | `tests/test_git_metadata.py` |
| 3.10 | TestDatabase unit tests (13 tests) | Complete | `tests/test_test_database.py` |

---

## 4. Structured Evaluation & Grading

LLM answer evaluation using a 6-tier grading model (Tier 0–6).

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 4.1 | Binary grading (0/1) | Complete | `GradeResult` enforces `score in (0, 1)` |
| 4.2 | JSON-only grader contracts | Complete | Strict structured output |
| 4.3 | Safety grading with confidence | Complete | `SafetyGrader` returns 0.0–1.0 confidence |
| 4.4 | Safety keywords (11 keywords) | Complete | `src/rfc/safety_keywords.py` |
| 4.5 | Safety test suites (4 `.robot` files) | Complete | Injection, extraction, jailbreak, indirect |
| 4.6 | Multi-score rubrics (0–5) | Planned | Requires `GradeResult` redesign |
| 4.7 | Partial credit support | Planned | Requires grader prompt + schema changes |
| 4.8 | Tolerance rules (numeric ranges) | Planned | `3.14` ≈ `3.1416` for math tests |
| 4.9 | Canonical answer normalization | Planned | Strip whitespace, units, formatting |
| 4.10 | Grader validation suite | Planned | Known question/answer/grade triples to validate graders |

### Grading Tier Model

| Tier | Name | Status |
|------|------|--------|
| Tier 0 | Pure Robot (deterministic asserts) | Complete |
| Tier 1 | Robot + Python (custom libraries) | Complete |
| Tier 2 | Robot + LLM (single grader) | Planned |
| Tier 3 | Robot + LLMs (consensus, 3+ models) | Planned |
| Tier 4 | Robot + LLMs + Docker (sandboxed execution) | Planned |
| Tier 5 | Other (external services, human-in-the-loop) | Planned |
| Tier 6 | None (data collection only, no pass/fail) | Planned |

---

## 5. Docker & Container Testing

Sandboxed code execution in disposable containers.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 5.1 | Container manager | Complete | `src/rfc/container_manager.py` |
| 5.2 | Docker keywords (7 keywords) | Complete | `src/rfc/docker_keywords.py` |
| 5.3 | Container profiles (MINIMAL/STANDARD/PERFORMANCE) | Complete | `config/test_suites.yaml` |
| 5.4 | Python code execution tests | Complete | `robot/40__tier4/docker/python/tests/` |
| 5.5 | Shell command execution tests | Complete | `robot/40__tier4/docker/shell/tests/` |
| 5.6 | Multi-model LLM-in-Docker tests | Complete | `robot/40__tier4/docker/llm/tests/` |
| 5.7 | Dynamic port allocation | Complete | `Find Available Port` keyword |
| 5.8 | Resource limits (CPU/memory/disk) | Complete | Configurable per-container |

---

## 6. CI/CD Pipeline

GitHub Actions CI (GitLab CI support removed — rfc-monorepo #106/#107).

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 6.1 | Modular CI scripts (`ci/*.sh`) | Complete | 8+ scripts, all `set -euo pipefail` |
| 6.2 | Dynamic pipeline generation | Removed (2026-06-10 audit) | generator deleted; GitLab CI removed (#106) |
| 6.3 | Ollama network discovery | Complete | `scripts/discover_nodes.py` |
| 6.4 | GitHub mirror sync | Superseded | Mirror publishes flow via `publish.sh --pr`; GitLab sync workflows removed (#106) |
| 6.5 | Claude Code review stage | Replaced (2026-06-10 audit) | Codex auto-review + Claude heartbeat sweep |
| 6.6 | Repo metrics + MR comments | Complete | `ci/report.sh` |
| 6.7 | `.env` sourcing in CI scripts | Complete | CI scripts source `.env` when present |
| 6.8 | Single-source config (YAML) | Complete | `config/test_suites.yaml` drives dashboard + CI |
| 6.9 | Env var → YAML overlays | Complete | `suite_config.py` applies runtime overrides |
| 6.10 | GitHub Actions workflow | Functional | `.github/workflows/robot-tests.yml` — primary CI |
| 6.11 | PyPI publishing in CI | Complete | `publish-pypi` job, `ci/release.sh` |
| 6.12 | Pipeline node auto-discovery | Planned | Ping nodes before scheduling jobs |
| 6.13 | Model-to-node assignment config | Planned | `config/model_assignments.yaml` |
| 6.14 | Node-to-GitLab-tag mapping | Removed | GitLab CI support removed (#106/#107) |
| 6.15 | Coverage thresholds in CI | Planned | Enforce minimum coverage as CI gate |
| 6.16 | Semver auto-bump on merge to main | Planned | Derive from conventional commit prefixes |
| 6.17 | Auto-generated CHANGELOG | Planned | From conventional commits via `git-cliff` or similar |

---

## 7. LLM Core Library

The Python library (`src/rfc/`) for LLM interaction and testing.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 7.1 | Ollama HTTP client | Complete | `src/rfc/ollama.py` |
| 7.2 | Robot Framework LLM keywords | Complete | `src/rfc/keywords.py` — `Ask LLM`, `Grade Answer` |
| 7.3 | Grader module | Complete | `src/rfc/grader.py` — pure evaluation functions |
| 7.4 | Shared data models | Complete | `src/rfc/models.py` — dataclasses |
| 7.5 | Suite configuration loader | Complete | `src/rfc/suite_config.py` — YAML + env overlays |
| 7.6 | `/api/show` integration | Planned | `OllamaClient.show_model()` for metadata |
| 7.7 | LLM client abstraction | Planned | Generic interface for Ollama + future providers |
| 7.8 | Ollama response metadata capture | Planned | Return `eval_count`, `eval_duration` from generate |

---

## 8. Robot Framework Test Suites

Integration test suites under `robot/`.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 8.1 | Math reasoning tests | Complete | `robot/20__tier2/math/tests/` |
| 8.2 | Docker execution tests (Python, shell, LLM) | Complete | `robot/40__tier4/docker/*/tests/` |
| 8.3 | Safety tests (injection, extraction, jailbreak, indirect) | Complete | `robot/20__tier2/safety/tests/` |
| 8.4 | Dashboard Playwright tests | Complete | `robot/dashboard/tests/` |
| 8.5 | Tier tagging on all tests | Functional | Required by rules; compliance not fully audited |
| 8.6 | Tool-call testing | Planned | Structured function call generation |
| 8.7 | Multi-turn conversation testing | Planned | Context retention across turns |
| 8.8 | Humor evaluation | Planned | Subjective, Tier 2–3 grading |
| 8.9 | Storytelling evaluation | Planned | Narrative coherence checks |
| 8.10 | Role-play evaluation | Planned | Character consistency across turns |
| 8.11 | Model metadata collection suite | Planned | `robot/10__tier1/ci/model_metadata.robot` |

---

## 9. LLM Manager (Multi-Model Orchestration)

Side-by-side multi-model testing and comparison.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 9.1 | Multi-model configuration | Planned | Single config for N endpoints |
| 9.2 | Parallel prompt execution | Planned | Same prompt → multiple models concurrently |
| 9.3 | Response comparison | Planned | Side-by-side grading |
| 9.4 | Model routing by capability | Planned | Tag-based selection (e.g., `coding` → codellama) |
| 9.5 | Fallback chains | Planned | Auto-failover when model unavailable |
| 9.6 | `Ask Multiple LLMs` keyword | Planned | New Robot Framework keyword |

---

## 10. Packaging & Distribution

PyPI packaging as `robotframework-chat`.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 10.1 | PyPI package name reserved | Complete | `robotframework-chat` on PyPI |
| 10.2 | `pyproject.toml` packaging config | Complete | Project metadata, classifiers, entry points |
| 10.3 | CI auto-publish on tag | Complete | `v*` tags trigger `ci/release.sh` |
| 10.4 | Cross-platform task runner | Complete | `tasks.py` — works on Windows without make/bash |
| 10.5 | Template documentation | Planned | "How to use RFC as a template" guide |

---

## 11. Code Quality & Testing Infrastructure

Static analysis, test coverage, and development tooling.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 11.1 | Linting (ruff) | Complete | Pre-commit hook + CI stage |
| 11.2 | Auto-formatting (ruff format) | Complete | Pre-commit hook |
| 11.3 | Type checking (mypy) | Complete | Pre-commit hook + CI stage |
| 11.4 | YAML/JSON validation | Complete | Pre-commit hooks |
| 11.5 | Dependency vulnerability scanning | Complete | `pip-audit`, `make code-quality-audit` |
| 11.6 | Test coverage measurement | Complete | `pytest-cov`, 85% overall line coverage |
| 11.7 | Pre-commit hooks | Complete | ruff, mypy, YAML/JSON, merge-conflict, whitespace |
| 11.8 | Unit test suite (~714 tests) | Complete | 37 of 39 modules covered |
| 11.9 | Coverage thresholds in CI | Planned | Enforce minimum (e.g., 70%) as gate |
| 11.10 | Mutation testing | Planned | No framework selected |
| 11.11 | Dead code detection | Planned | vulture or similar |

---

## 12. Resilience & Error Handling

Graceful degradation for infrastructure and model failures.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 12.1 | Retry with backoff for infra failures | Planned | Ollama down, DB unreachable |
| 12.2 | Distinguish infra vs. model failures | Planned | Infra failures don't count against model scores |
| 12.3 | Local result buffering | Planned | Buffer if DB unreachable, sync later |
| 12.4 | Graceful node offline handling | Planned | Skip remaining tests, continue with other nodes |
| 12.5 | `WARN` for transient, `FAIL` for persistent | Planned | Robot Framework log levels |

---

## 13. Multimodal Testing

Image + text, audio + text prompt support.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 13.1 | Image + text prompts | Planned | Depends on structured evaluation (§4) |
| 13.2 | Audio + text prompts (ASR/TTS) | Planned | |
| 13.3 | Multimodal grading | Planned | |
| 13.4 | Artifact versioning and replay | Planned | |

---

## 14. MCP & Multi-Agent Testing

Testing coordinated AI systems. Depends on LLM Manager (§9).

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 14.1 | MCP integration | Planned | |
| 14.2 | Multi-model chat orchestration | Planned | |
| 14.3 | Agent-to-agent communication | Planned | |
| 14.4 | Task execution framework | Planned | |

---

## 15. A/B Evaluation Pipelines

Scientific measurement of model changes. Depends on multi-score rubrics (§4)
and LLM Manager (§9).

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 15.1 | A/B testing framework | Planned | |
| 15.2 | Prompt vs. model comparison | Planned | |
| 15.3 | Dataset replay | Planned | |
| 15.4 | Statistical comparison | Planned | |
| 15.5 | Regression gating in CI | Planned | |

---

## 16. Agentic Workflows & Playwright

Robot Framework Tasks and browser automation for AI-driven workflows.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 16.1 | Playwright-based web automation | Planned | Robot Framework + Browser library |
| 16.2 | Robot Framework Tasks (`*** Tasks ***`) | Planned | RPA-style non-test automation |
| 16.3 | Automated dashboard validation | Planned | Superset/Grafana interaction tests |

---

## 17. TRON-Themed Dashboards (Deferred to v2+)

Grafana dashboards with TRON aesthetic. Deferred along with Grafana/Loki.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 17.1 | TRON color palette and theme | Planned | Cyan, electric blue, black, orange |
| 17.2 | "The Grid" — node health matrix | Planned | Glowing when active |
| 17.3 | "Light Cycle Arena" — A/B comparison | Planned | Model-vs-model |
| 17.4 | "Identity Disc" — per-model radar chart | Planned | Accuracy, speed, safety, cost |
| 17.5 | "MCP Dashboard" — master overview | Planned | All test runs |
| 17.6 | Public read-only anonymous access | Planned | Grafana anonymous viewer role |

---

## 18. Dash Dashboard (Deprecated)

> **Owner decision (2026-02-19):** The Dash dashboard is a prototype.
> Superset is the v1 dashboard. Do not invest further.

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 18.1 | Multi-session management (5 tabs) | Deprecated | `dashboard/core/session_manager.py` |
| 18.2 | Test runner with live output | Deprecated | `dashboard/core/robot_runner.py` |
| 18.3 | Auto-recovery on failure | Deprecated | 3 max attempts |
| 18.4 | Session controls (run/stop/replay/delete) | Deprecated | |
| 18.5 | Suite/IQ/model/profile dropdowns | Deprecated | Populated from config |
| 18.6 | Result upload to database | Deprecated | Export button per session |
| 18.7 | Ollama Hosts monitoring tab | Deprecated | Polls `/api/tags` + `/api/ps` |
| 18.8 | GitLab Pipelines monitoring tab | Removed | GitLab CI support removed (#106/#107) |
| 18.9 | Playwright browser tests | Deprecated | `robot/dashboard/tests/` |

---

## Summary

| Category | Complete | Functional | Planned | Deprecated |
|----------|----------|------------|---------|------------|
| 1. Database & Reporting | 5 | 0 | 8 | 0 |
| 2. Visualization (Superset) | 8 | 1 | 4 | 0 |
| 3. Listener Infrastructure | 10 | 0 | 0 | 0 |
| 4. Structured Evaluation | 5 | 0 | 5 | 0 |
| 5. Docker & Container Testing | 8 | 0 | 0 | 0 |
| 6. CI/CD Pipeline | 11 | 1 | 5 | 0 |
| 7. LLM Core Library | 5 | 0 | 3 | 0 |
| 8. Robot Framework Test Suites | 4 | 1 | 6 | 0 |
| 9. LLM Manager | 0 | 0 | 6 | 0 |
| 10. Packaging & Distribution | 4 | 0 | 1 | 0 |
| 11. Code Quality & Testing | 8 | 0 | 3 | 0 |
| 12. Resilience & Error Handling | 0 | 0 | 5 | 0 |
| 13. Multimodal Testing | 0 | 0 | 4 | 0 |
| 14. MCP & Multi-Agent | 0 | 0 | 4 | 0 |
| 15. A/B Evaluation Pipelines | 0 | 0 | 5 | 0 |
| 16. Agentic Workflows | 0 | 0 | 3 | 0 |
| 17. TRON Dashboards (v2+) | 0 | 0 | 6 | 0 |
| 18. Dash Dashboard | 0 | 0 | 0 | 9 |
| **Total** | **68** | **3** | **68** | **9** |

**Overall: 68 complete (46%), 3 functional (2%), 68 planned (46%), 9 deprecated (6%)**

---

*Last updated: 2026-03-04*
