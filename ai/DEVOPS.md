# DevOps Practices Tracker

Comprehensive list of DevOps practices applicable to robotframework-chat,
with current adoption status.

Updated as of 2026-02-17.

**Legend:** Adopted / Partial / Not Started

---

## 1. Source Control & Branching

| Practice | Status | Notes |
|----------|--------|-------|
| Git version control | Adopted | Git repo with GitLab primary, GitHub mirror |
| Branch protection rules | Partial | GitLab MR workflow exists; branch protection rules not verified |
| Conventional commit messages | Not Started | No enforced commit message format |
| Signed commits | Not Started | No GPG/SSH signing requirement |
| Git hooks (pre-commit) | Adopted | `.pre-commit-config.yaml` — ruff, mypy, YAML/JSON checks |
| Post-commit Robot test hook | Adopted | Runs modified `.robot` files on commit |
| Monorepo structure | Adopted | Single repo for library, dashboard, CI, tests |

---

## 2. Continuous Integration

| Practice | Status | Notes |
|----------|--------|-------|
| CI pipeline on every push | Adopted | `.gitlab-ci.yml` — 7 stages |
| CI on merge requests | Adopted | Lint, test, report stages run on MR events |
| GitHub Actions CI | Adopted | `.github/workflows/robot-tests.yml` — lint, dashboard pytest, dry-run, robot tests |
| Dynamic pipeline generation | Adopted | `scripts/generate_pipeline.py` generates child pipelines from `config/test_suites.yaml` |
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
| Unit tests (pytest) | Adopted | 23 test files, ~537 test functions |
| Robot Framework integration tests | Adopted | Math, Docker, safety test suites |
| Browser/E2E tests (Playwright) | Adopted | Dashboard Playwright tests via Robot Framework |
| Test result archival | Adopted | DbListener writes to SQLite/PostgreSQL |
| Test coverage measurement | Not Started | No `pytest-cov` or coverage configuration |
| Coverage thresholds/gates | Not Started | No minimum coverage enforcement in CI |
| Mutation testing | Not Started | No mutation testing framework |
| Load/performance testing | Not Started | No load tests for dashboard or API |
| Contract testing | Not Started | No API contract verification |
| Property-based testing | Not Started | No Hypothesis or similar framework |

### Pytest Coverage Map

| Source Area | Modules Tested | Total Modules | Coverage % | Test Count |
|-------------|---------------|---------------|------------|------------|
| `src/rfc/` | 15 | 20 | 75% | ~279 |
| `dashboard/core/` | 6 | 6 | 100% | ~127 |
| `dashboard/` | 3 | 5 | 60% | ~28 |
| `scripts/` | 3 | 8 | 37% | ~135 |
| **Total** | **27** | **39** | **69%** | **~537** |

#### Modules Without Tests

- `src/rfc/container_manager.py` — Container lifecycle management
- `src/rfc/docker_keywords.py` — Docker Robot Framework keywords
- `src/rfc/dry_run_listener.py` — Dry run listener
- `src/rfc/keywords.py` — Core Robot Framework keywords
- `src/rfc/pre_run_modifier.py` — Pre-run test modifier
- `src/rfc/safety_keywords.py` — Safety Robot Framework keywords
- `scripts/discover_nodes.py` — Ollama node discovery
- `scripts/discover_ollama.py` — Ollama service discovery
- `scripts/generate_ci_metadata.py` — CI metadata generation
- `scripts/generate_pipeline.py` — Pipeline YAML generation
- `scripts/query_results.py` — Result querying
- `scripts/repo_metrics.py` — Repository metrics

---

## 5. Code Quality

| Practice | Status | Notes |
|----------|--------|-------|
| Linting (ruff) | Adopted | `make code-lint`, pre-commit hook, CI stage |
| Auto-formatting (ruff format) | Adopted | `make code-format`, pre-commit hook |
| Type checking (mypy) | Adopted | `make code-typecheck`, pre-commit hook |
| YAML/JSON validation | Adopted | Pre-commit hooks: `check-yaml`, `check-json` |
| Trailing whitespace / EOF fixer | Adopted | Pre-commit hooks |
| Merge conflict detection | Adopted | Pre-commit hook: `check-merge-conflict` |
| Dependency pinning | Adopted | `pyproject.toml` with pinned versions |
| Dependency vulnerability scanning | Not Started | No `pip-audit`, Dependabot, or Snyk |
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
| Docker Compose orchestration | Adopted | 5 services: postgres, redis, superset-init, superset, dashboard |
| Multi-stage Docker builds | Partial | `superset/Dockerfile` and `dashboard/Dockerfile` exist; CI uses `Dockerfile.ci` |
| Container resource limits | Adopted | Container profiles (MINIMAL/STANDARD/PERFORMANCE) |
| Docker health checks | Adopted | All services have health checks |
| Container image pinning | Adopted | `postgres:16-alpine`, `redis:7-alpine` |
| Container registry | Not Started | No private registry; images built locally |
| Kubernetes/orchestration | Not Started | Docker Compose only |
| Infrastructure as Code (IaC) | Not Started | No Terraform, Pulumi, etc. |
| Network segmentation | Adopted | `rfc-net` bridge network for service isolation |

---

## 8. Monitoring & Observability

| Practice | Status | Notes |
|----------|--------|-------|
| Superset analytics dashboard | Partial | Charts view working; full dashboard incomplete |
| Ollama host monitoring | Adopted | Dashboard polls `/api/tags` + `/api/ps`, 24hr ring buffer |
| GitLab pipeline monitoring | Adopted | Real-time pipeline status table in dashboard |
| Repo metrics reporting | Adopted | `ci/report.sh` generates metrics, posts to MR |
| Application logging | Partial | Python logging in listeners; no centralized logging |
| Structured logging (JSON) | Not Started | No structured log format |
| Log aggregation (ELK/Loki) | Not Started | No centralized log collection |
| APM / distributed tracing | Not Started | No OpenTelemetry, Datadog, etc. |
| Alerting (PagerDuty/OpsGenie) | Not Started | No alerting integration |
| Uptime monitoring | Not Started | No external health checks |
| Error tracking (Sentry) | Not Started | No error tracking service |
| Dashboard SLOs/SLIs | Not Started | No service level objectives defined |

---

## 9. Documentation

| Practice | Status | Notes |
|----------|--------|-------|
| AI agent docs (`ai/AGENTS.md`) | Adopted | Core philosophy and agent guidelines |
| Feature tracker (`ai/FEATURES.md`) | Adopted | Priority-ordered feature status |
| Pipeline docs (`ai/PIPELINES.md`) | Adopted | CI pipeline documentation |
| Dev guide (`ai/DEV.md`) | Adopted | Developer onboarding |
| Refactoring notes (`ai/REFACTOR.md`) | Adopted | Refactoring plans |
| DevOps tracker (`ai/DEVOPS.md`) | Adopted | This document |
| API documentation | Not Started | No OpenAPI/Swagger or generated docs |
| Architecture decision records (ADRs) | Not Started | No formal decision log |
| Runbook / incident response | Not Started | No operational runbooks |
| Changelog | Not Started | No CHANGELOG.md or automated generation |

---

## 10. Release Management

| Practice | Status | Notes |
|----------|--------|-------|
| Semantic versioning | Adopted | `v0.2.0` in `pyproject.toml` |
| Version command | Partial | `make version` exists but marked not complete |
| Git tags for releases | Not Started | No release tags |
| Automated release notes | Not Started | No changelog generation |
| Package publishing (PyPI) | Not Started | Build system configured but not published |
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
| A/B testing framework | Not Started | Planned in FEATURES.md Priority 6+ |
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
| Dependency vulnerability scanning | Not Started | No `pip-audit` or Dependabot |
| Network policies | Partial | Docker bridge network; no firewall rules |
| RBAC for Superset | Partial | Admin user auto-created; no role hierarchy |

---

## Summary

| Category | Adopted | Partial | Not Started | Total |
|----------|---------|---------|-------------|-------|
| Source Control & Branching | 5 | 1 | 2 | 8 |
| Continuous Integration | 9 | 1 | 2 | 12 |
| Continuous Deployment | 3 | 0 | 4 | 7 |
| Testing | 4 | 0 | 6 | 10 |
| Code Quality | 7 | 0 | 4 | 11 |
| Configuration & Secrets | 5 | 1 | 1 | 7 |
| Containerization & Infrastructure | 5 | 1 | 2 | 8 |
| Monitoring & Observability | 3 | 2 | 7 | 12 |
| Documentation | 6 | 0 | 4 | 10 |
| Release Management | 1 | 1 | 4 | 6 |
| MLOps | 3 | 2 | 5 | 10 |
| Security | 1 | 2 | 5 | 8 |
| **Total** | **52** | **11** | **46** | **109** |

**Overall adoption: 52/109 practices adopted (48%), 11 partial (10%), 46 not started (42%)**

### Top Priorities for DevOps Improvement

1. **Test coverage measurement** — Add `pytest-cov` and enforce minimum
   coverage thresholds in CI. The 12 untested modules are the immediate gap.
2. **Dependency vulnerability scanning** — Add `pip-audit` to CI or enable
   Dependabot on the GitHub mirror.
3. **Structured logging** — Adopt JSON logging for listeners and dashboard
   to enable future log aggregation.
4. **Container image scanning** — Add Trivy or Grype scan to CI pipeline.
5. **Changelog and release tags** — Automate changelog generation and tag
   releases for traceability.
