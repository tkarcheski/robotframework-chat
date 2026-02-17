# robotframework-chat Makefile
# Run `make help` for a list of targets.

COMPOSE  := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || { echo "Error: Docker Compose V2 is required. Install it with: https://docs.docker.com/compose/install/" >&2; echo "false"; })
ROBOT    := uv run robot
LISTENER := --listener rfc.db_listener.DbListener --listener rfc.git_metadata_listener.GitMetaData --listener rfc.ollama_timestamp_listener.OllamaTimestampListener
DRYRUN_LISTENER := --listener rfc.dry_run_listener.DryRunListener

# Load .env if present
-include .env
export

.PHONY: help install docker-up docker-down docker-restart docker-logs bootstrap \
        robot robot-math robot-docker robot-safety robot-dryrun \
        robot-math-import robot-import \
        test-dashboard test-dashboard-playwright \
        import code-lint code-format code-typecheck code-check code-coverage code-audit version \
        ci-lint ci-test ci-generate ci-report ci-deploy ci-test-dashboard \
        opencode-pipeline-review opencode-local-review \
        ci-sync ci-sync-db ci-status ci-list-pipelines ci-list-jobs ci-fetch-artifact ci-verify-db

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────

install: ## Install Python dependencies
	uv sync --extra dev --extra dashboard --extra superset

# ── Docker / Superset ─────────────────────────────────────────────────

.env: ## Create .env from .env.example if missing
	cp .env.example .env
	@echo "Created .env from .env.example – edit it if needed."

docker-up: .env ## Start PostgreSQL + Redis + Superset + Dashboard
	$(COMPOSE) up -d

docker-down: ## Stop all services
	$(COMPOSE) down

docker-restart: ## Restart all services
	$(COMPOSE) restart

docker-logs: ## Tail service logs
	$(COMPOSE) logs -f

bootstrap: ## First-time Superset setup (run after 'make docker-up')
	$(COMPOSE) run --rm superset-init

# ── Robot Framework Tests ─────────────────────────────────────────────

robot: robot-math robot-docker robot-safety ## Run all Robot Framework test suites

robot-math: ## Run math tests (Robot Framework)
	$(ROBOT) -d results/math $(LISTENER) robot/math/tests/

robot-docker: ## Run Docker tests (Robot Framework)
	$(ROBOT) -d results/docker $(LISTENER) robot/docker/

robot-safety: ## Run safety tests (Robot Framework)
	$(ROBOT) -d results/safety $(LISTENER) robot/safety/

robot-math-import: ## Run math tests then import results (continues on test failures)
	-$(ROBOT) -d results/math $(LISTENER) robot/math/tests/
	$(MAKE) import

robot-import: ## Run all tests then import results (continues on test failures)
	-$(ROBOT) -d results/math $(LISTENER) robot/math/tests/
	-$(ROBOT) -d results/docker $(LISTENER) robot/docker/
	-$(ROBOT) -d results/safety $(LISTENER) robot/safety/
	$(MAKE) import

robot-dryrun: ## Validate all Robot tests (dry run, no execution)
	$(ROBOT) --dryrun -d results/dryrun $(DRYRUN_LISTENER) robot/

# ── Dashboard Tests ──────────────────────────────────────────────────

test-dashboard: ## Run dashboard pytest unit tests
	uv run pytest tests/test_dashboard_layout.py tests/test_dashboard_monitoring.py -v

test-dashboard-playwright: ## Run dashboard Playwright browser self-tests
	bash ci/test_dashboard.sh playwright

import: ## Import results from output.xml files: make import RESULTS_DIR=results/
	uv run python scripts/import_test_results.py $(or $(RESULTS_DIR),results/) -r

# ── Code quality ──────────────────────────────────────────────────────

code-lint: ## Run ruff linter
	uv run ruff check .

code-format: ## Auto-format code
	uv run ruff format .

code-typecheck: ## Run mypy type checker
	uv run mypy src/

code-check: code-lint code-typecheck ## Run all code quality checks

code-coverage: ## Run pytest with coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html:htmlcov

code-audit: ## Audit dependencies for known vulnerabilities
	uv run pip-audit

# ── CI Scripts ────────────────────────────────────────────────────────
# Thin wrappers around ci/*.sh for use in .gitlab-ci.yml and locally.

ci-lint: ## Run CI lint checks (all, or: make ci-lint CHECK=ruff)
	bash ci/lint.sh $(or $(CHECK),all)

ci-test: ## Run CI tests with health checks (all, or: make ci-test SUITE=math)
	bash ci/test.sh $(or $(SUITE),all)

ci-generate: ## Generate child pipeline YAML (regular|dynamic|discover)
	bash ci/generate.sh $(or $(MODE),regular)

ci-report: ## Generate repo metrics (add POST_MR=1 to post to MR)
	bash ci/report.sh $(if $(POST_MR),--post-mr,)

ci-deploy: ## Deploy Superset to remote host
	bash ci/deploy.sh

ci-test-dashboard: ## Run dashboard tests in CI (all, or: make ci-test-dashboard MODE=pytest)
	bash ci/test_dashboard.sh $(or $(MODE),all)

# ── AI Review ────────────────────────────────────────────────────────

opencode-pipeline-review: ## Run OpenCode AI review in CI (pipeline failures + MR diff)
	bash ci/review.sh

opencode-local-review: ## Run OpenCode AI review on local uncommitted/branch changes
	bash ci/local_review.sh

# ── GitLab CI ────────────────────────────────────────────────────────

ci-status: ## Check GitLab API connectivity
	uv run python scripts/sync_ci_results.py status

ci-list-pipelines: ## List recent CI pipelines
	uv run python scripts/sync_ci_results.py list-pipelines

ci-list-jobs: ## List jobs in a pipeline: make ci-list-jobs PIPELINE=<id>
	uv run python scripts/sync_ci_results.py list-jobs $(PIPELINE)

ci-fetch-artifact: ## Download a single job artifact: make ci-fetch-artifact JOB=<id>
	uv run python scripts/sync_ci_results.py fetch-artifact $(JOB)

ci-sync-db: ## Sync CI pipeline results to database
	uv run python scripts/sync_ci_results.py sync

ci-verify-db: ## Verify database contents after sync
	uv run python scripts/sync_ci_results.py verify

ci-backfill: ## Backfill all GitLab pipeline data to database
	uv run python scripts/sync_ci_results.py backfill

ci-backfill-metadata: ## Store pipeline metadata only (no artifact download)
	uv run python scripts/sync_ci_results.py backfill --metadata-only

ci-list-pipeline-results: ## List pipeline_results stored in database
	uv run python scripts/sync_ci_results.py list-pipeline-results

# ── Versioning ────────────────────────────────────────────────────────

version: ## Print current version
	@uv run python -c "from rfc import __version__; print(__version__)"
