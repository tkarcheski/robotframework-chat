# DevOps Practices Tracker

Comprehensive list of DevOps practices applicable to robotframework-chat,
with current adoption status.

Updated as of 2026-02-17. Owner decisions from spec review added 2026-02-19.

> **Cross-references:** See `ai/testing.md` for grading tiers and test rules,
> `humans/TODO.md` for actionable items.

**Legend:** Adopted / Partial / Not Started

---

## 1. Source Control & Branching

| Practice | Status | Notes |
|----------|--------|-------|
| Git version control | Adopted | Git repo on GitHub (GitLab support removed, rfc-monorepo #106/#107) |
| Branch protection rules | Partial | GitHub PR workflow exists; branch protection rules not verified |
| Conventional commit messages | Not Started | No enforced commit message format |
| Signed commits | Not Started | No GPG/SSH signing requirement |
| Git hooks (pre-commit) | Adopted | `.pre-commit-config.yaml` — ruff, mypy, YAML/JSON checks |
| Post-commit Robot test hook | Adopted | Runs modified `.robot` files on commit |
| Monorepo structure | Adopted | Single repo for library, dashboard, CI, tests |

---

## 2. Continuous Integration

| Practice | Status | Notes |
|----------|--------|-------|
| CI pipeline on every push | Adopted | GitHub Actions (`.github/workflows/robot-tests.yml`) |
| CI on merge requests | Adopted | Lint, test, report stages run on MR events |
| GitHub Actions CI | Adopted | `.github/workflows/robot-tests.yml` — lint, dashboard pytest, dry-run, robot tests |
| Dynamic pipeline generation | Retired (2026-06-10 audit) | generator deleted; GitLab CI itself removed (#106/#107) |
| Scheduled pipelines | Adopted | Hourly cron triggers dynamic pipeline with full node/model matrix |
| Pipeline artifact collection | Adopted | Test results, metrics, review artifacts archived |
| JUnit report integration | Adopted | Dashboard pytest produces `pytest-results.xml` |
| Dry-run validation | Adopted | `robot --dryrun` validates all `.robot` files without execution |
| CI script modularity | Adopted | 11 scripts in `ci/` — all use `set -euo pipefail` |
| Parallel test execution | Partial | Dynamic pipeline runs multiple suites; no intra-suite parallelism |
| Flaky test detection | Not Started | No retry/quarantine mechanism for intermittent failures |
| CI caching | Not Started | No uv/pip cache between pipeline runs |

---

## 3. Continuous Deployment

| Practice | Status | Notes |
|----------|--------|-------|
| Automated Superset deployment | Adopted | `ci/deploy.sh` deploys on main branch push |
| Docker Compose production stack | Adopted | PostgreSQL + Redis + Superset + Dashboard |
| Container health checks | Adopted | All services have Docker health checks |
| Blue/green or canary deploys | Not Started | Single-target deployment only |
| Rollback procedures | Not Started | No automated rollback on failed deploy |
| Deployment notifications | Not Started | No Slack/email/webhook on deploy status |
| Environment promotion (staging → prod) | Not Started | Single environment only |

---

## 4. Testing

| Practice | Status | Notes |
|----------|--------|-------|
| Unit tests (pytest) | Adopted | `uv run pytest` |
| Robot Framework integration tests | Adopted | Math, Docker, safety test suites |
| Browser/E2E tests (Playwright) | Adopted | Dashboard Playwright tests via Robot Framework |
| Test result archival | Adopted | DbListener writes to SQLite/PostgreSQL |
| Test coverage measurement | Adopted | `pytest-cov` configured, `make code-quality-coverage` target |
| Coverage thresholds/gates | Not Started | No minimum coverage enforcement in CI |
| Mutation testing | Not Started | No mutation testing framework |
| Load/performance testing | Not Started | No load tests for dashboard or API |
| Contract testing | Not Started | No API contract verification |
| Property-based testing | Not Started | No Hypothesis or similar framework |

---

## 5. Code Quality

| Practice | Status | Notes |
|----------|--------|-------|
| Linting (ruff) | Adopted | `make code-quality-lint`, pre-commit hook, CI stage |
| Auto-formatting (ruff format) | Adopted | `make code-quality-format`, pre-commit hook |
| Type checking (mypy) | Adopted | `make code-quality-typecheck`, pre-commit hook |
| YAML/JSON validation | Adopted | Pre-commit hooks: `check-yaml`, `check-json` |
| Trailing whitespace / EOF fixer | Adopted | Pre-commit hooks |
| Merge conflict detection | Adopted | Pre-commit hook: `check-merge-conflict` |
| Dependency pinning | Adopted | `pyproject.toml` with pinned versions |
| Dependency vulnerability scanning | Adopted | `pip-audit` in dev deps, `make code-quality-audit` target |
| License compliance scanning | Not Started | No license checker |
| Code complexity limits | Not Started | No cyclomatic complexity gates |
| Dead code detection | Not Started | No vulture or similar tool |

---

## 6. Configuration & Secrets Management

| Practice | Status | Notes |
|----------|--------|-------|
| `.env` file configuration | Adopted | `.env.example` template, auto-created by Makefile |
| Environment variable overrides | Adopted | `suite_config.py` applies env var overlays on YAML config |
| Single-source config (YAML) | Adopted | `config/test_suites.yaml` drives dashboard + CI |
| Secrets in environment variables | Adopted | DB passwords, API tokens via `.env` |
| Secrets vault integration | Not Started | No HashiCorp Vault, AWS Secrets Manager, etc. |
| `.env` file in `.gitignore` | Adopted | Prevents accidental secret commits |
| Config validation on startup | Partial | `suite_config.py` validates; `.env` not validated |

---

## 7. Containerization & Infrastructure

| Practice | Status | Notes |
|----------|--------|-------|
| Docker Compose orchestration | Adopted | 4 services: postgres, redis, superset-init, superset |
| Multi-stage Docker builds | Partial | `superset/Dockerfile` and `dashboard/Dockerfile` exist; CI uses `Dockerfile.ci` |
| Container resource limits | Adopted | Container profiles (MINIMAL/STANDARD/PERFORMANCE) |
| Docker health checks | Adopted | All services have health checks |
| Container image pinning | Adopted | `postgres:16-alpine`, `redis:7-alpine` |
| Container registry | Not Started | No private registry; images built locally |
| Kubernetes/orchestration | Deferred (v2+) | Docker Compose only; K8s deferred to post-v1 |
| Infrastructure as Code (IaC) | Not Started | No Terraform, Pulumi, etc. |
| Network segmentation | Adopted | `rfc-net` bridge network for service isolation |

---

## 8. Monitoring & Observability

| Practice | Status | Notes |
|----------|--------|-------|
| Superset analytics dashboard | Partial | Charts view working; full dashboard incomplete |
| Ollama host monitoring | Adopted | Dashboard polls `/api/tags` + `/api/ps`, 24hr ring buffer |
| Repo metrics reporting | Removed | GitLab CI support removed (rfc-monorepo #106/#107) |
| Application logging | Partial | Python logging in listeners; no centralized logging |
| Structured logging (JSON) | Not Started | No structured log format |
| Log aggregation (ELK/Loki) | Deferred (v2+) | Loki listener removed; deferred to post-v1 |
| Log aggregation (Graylog/GELF) | Opt-in | Private `modules/graylog` submodule; lifecycle + per-LLM-call GELF streams. Off by default — docs live with the private module |
| APM / distributed tracing | Not Started | No OpenTelemetry, Datadog, etc. |
| Alerting (PagerDuty/OpsGenie) | Not Started | No alerting integration |
| Uptime monitoring | Not Started | No external health checks |
| Error tracking (Sentry) | Not Started | No error tracking service |
| Dashboard SLOs/SLIs | Not Started | No service level objectives defined |

---

## 9. Documentation

| Practice | Status | Notes |
|----------|--------|-------|
| AI agent docs (`ai/agents.md`) | Adopted | Core philosophy and agent guidelines |
| Requirements tracker (`docs/requirements.md`) | Adopted | Priority-ordered requirements and status |
| Pipeline docs (`ai/pipelines.md`) | Adopted | CI pipeline documentation |
| Dev guide (`ai/dev.md`) | Adopted | Developer onboarding |
| Refactoring notes (`ai/refactor.md`) | Adopted | Refactoring plans |
| DevOps tracker (`ai/devops.md`) | Adopted | This document |
| API documentation | Not Started | No OpenAPI/Swagger or generated docs |
| Architecture decision records (ADRs) | Not Started | No formal decision log |
| Runbook / incident response | Not Started | No operational runbooks |

---

## 10. Release Management

| Practice | Status | Notes |
|----------|--------|-------|
| Semantic versioning | Adopted | `pyproject.toml` + `src/rfc/__init__.py` |
| Version command | Adopted | `make version` prints current version |
| Git tags for releases | Adopted | `v*` tags trigger release pipeline |
| Package publishing (PyPI) | Adopted | `.github/workflows/pypi-publish.yml` builds + uploads on `v*` tags |
| GitHub Releases | Not Started | No release workflow |

---

## 11. AI/ML-Specific DevOps (MLOps)

| Practice | Status | Notes |
|----------|--------|-------|
| Model discovery | Adopted | `scripts/discover_ollama.py`, `scripts/discover_nodes.py` |
| Multi-model test matrix | Adopted | Dynamic pipeline generates per-model test jobs |
| Test result database | Adopted | PostgreSQL/SQLite dual-backend |
| Model comparison dashboards | Partial | Superset charts exist; cross-filtering not started |
| Model regression detection | Not Started | No automated pass-rate threshold alerts |
| Prompt versioning | Not Started | Prompts inline in .robot files, not versioned separately |
| Model evaluation rubrics | Partial | Binary 0/1 grading done; multi-score rubrics not started |
| A/B testing framework | Not Started | Planned in docs/requirements.md §15 |
| Dataset management | Not Started | No formal dataset versioning |
| Experiment tracking (MLflow/W&B) | Not Started | No experiment tracking platform |

---

## 12. Security

| Practice | Status | Notes |
|----------|--------|-------|
| Secret exclusion from VCS | Adopted | `.env` in `.gitignore` |
| Container image scanning | Not Started | No Trivy, Grype, or similar |
| SAST (static analysis security) | Not Started | No Bandit, Semgrep, etc. |
| DAST (dynamic analysis) | Not Started | No ZAP, Burp, etc. |
| Supply chain security (SBOM) | Not Started | No software bill of materials |
| Dependency vulnerability scanning | Adopted | `pip-audit` in dev deps, `make code-quality-audit` |
| Network policies | Partial | Docker bridge network; no firewall rules |
| RBAC for Superset | Partial | Admin user auto-created; no role hierarchy |

---

## Top Priorities for DevOps Improvement

1. ~~**Test coverage measurement**~~ Done — `pytest-cov` configured,
   `make code-quality-coverage` target added.
2. ~~**Dependency vulnerability scanning**~~ Done — `pip-audit` added to
   dev dependencies, `make code-quality-audit` target added.
3. **Coverage thresholds in CI** — Enforce minimum coverage (e.g. 70%) as
   a CI gate so regressions are caught automatically.
4. **Structured logging** — Adopt JSON logging for listeners and dashboard
   to enable future log aggregation.
5. **Container image scanning** — Add Trivy or Grype scan to CI pipeline.
6. **Script test coverage** — Add tests for the remaining untested scripts
   in `scripts/` (discovery, pipeline generation, metrics).

---

## Owner Decisions Affecting DevOps (2026-02-19 Spec Review)

These decisions from the spec review session impact DevOps practices:

| Decision | Impact | See |
|----------|--------|-----|
| 90-day data retention | Need cleanup cron/CI job | `humans/TODO.md` § Data Retention |
| Semver auto-bump on merge to main | Need CI pipeline rule + version script | `humans/TODO.md` § Versioning |
| Discord notifications (future) | New CI integration after DB/Superset stable | `humans/TODO.md` § Alerting |
| `make test-make` meta-target | Smoke-test all make targets | `humans/TODO.md` § CI/CD |
| Makefile parity with pipeline | Fix 24 broken targets | `docs/requirements.md` § CI/CD |
| Secrets stay in `.env` | No vault needed | `.env.example` |
| Branching: main / staging / claude/* | Document and enforce | `ai/pipelines.md` § Branching Model |
