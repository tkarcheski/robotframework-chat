# robotframework-chat Makefile
# Run `make help` for a list of targets.

COMPOSE  := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || { echo "Error: Docker Compose V2 is required. Install it with: https://docs.docker.com/compose/install/" >&2; echo "false"; })
ROBOT    := uv run robot
LISTENER := --listener rfc.db_listener.DbListener --listener rfc.git_metadata_listener.GitMetaData --listener rfc.ollama_timestamp_listener.OllamaTimestampListener

# Load .env if present
-include .env
export

.PHONY: help install up down restart logs bootstrap \
        test test-math test-docker test-safety test-dashboard test-dashboard-playwright \
        import lint format typecheck check version \
        ci-lint ci-test ci-generate ci-report ci-sync ci-sync-db ci-deploy ci-review ci-test-dashboard \
        ci-status ci-list-pipelines ci-list-jobs ci-fetch-artifact ci-verify-db

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────

install: ## Install Python dependencies
	uv sync --extra dev --extra dashboard --extra superset

# ── Docker / Superset ─────────────────────────────────────────────────

.env: ## Create .env from .env.example if missing
	cp .env.example .env
	@echo "Created .env from .env.example – edit it if needed."

up: .env ## Start PostgreSQL + Redis + Superset + Dashboard
	$(COMPOSE) up -d

down: ## Stop all services
	$(COMPOSE) down

restart: ## Restart all services
	$(COMPOSE) restart

logs: ## Tail service logs
	$(COMPOSE) logs -f

bootstrap: ## First-time Superset setup (run after 'make up')
	$(COMPOSE) run --rm superset-init

# ── Tests ─────────────────────────────────────────────────────────────

test: test-math test-docker test-safety ## Run all test suites

test-math: ## Run math tests
	$(ROBOT) -d results/math $(LISTENER) robot/math/tests/

test-docker: ## Run Docker tests
	$(ROBOT) -d results/docker $(LISTENER) robot/docker/

test-safety: ## Run safety tests
	$(ROBOT) -d results/safety $(LISTENER) robot/safety/

test-dashboard: ## Run dashboard pytest unit tests
	uv run pytest tests/test_dashboard_layout.py tests/test_dashboard_monitoring.py -v

test-dashboard-playwright: ## Run dashboard Playwright browser self-tests
	bash ci/test_dashboard.sh playwright

import: ## Import results from output.xml files: make import PATH=results/
	uv run python scripts/import_test_results.py $(or $(PATH),results/) -r

# ── Code quality ──────────────────────────────────────────────────────

lint: ## Run ruff linter
	uv run ruff check .

format: ## Auto-format code
	uv run ruff format .

typecheck: ## Run mypy type checker
	uv run mypy src/

check: lint typecheck ## Run all code quality checks

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

ci-sync: ## Mirror repo to GitHub
	bash ci/sync.sh

ci-sync-db: ## Sync CI pipeline results to database
	bash ci/sync_db.sh

ci-status: ## Check GitLab CI connection status
	bash ci/sync_db.sh status

ci-list-pipelines: ## List recent GitLab pipelines (REF=branch LIMIT=n)
	bash ci/sync_db.sh list-pipelines $(if $(REF),--ref $(REF),) $(if $(LIMIT),-n $(LIMIT),)

ci-list-jobs: ## List jobs from a pipeline: make ci-list-jobs PIPELINE=12345
	bash ci/sync_db.sh list-jobs $(PIPELINE)

ci-fetch-artifact: ## Download artifact: make ci-fetch-artifact JOB=67890
	bash ci/sync_db.sh fetch-artifact $(JOB) $(if $(ARTIFACT),--artifact-path $(ARTIFACT),) $(if $(OUT),-o $(OUT),)

ci-verify-db: ## Verify database contents after sync
	bash ci/sync_db.sh verify

ci-deploy: ## Deploy Superset to remote host
	bash ci/deploy.sh

ci-test-dashboard: ## Run dashboard tests in CI (all, or: make ci-test-dashboard MODE=pytest)
	bash ci/test_dashboard.sh $(or $(MODE),all)

ci-review: ## Run Claude Code review
	bash ci/review.sh

# ── Versioning ────────────────────────────────────────────────────────

version: ## Print current version
	@python -c "from src.rfc import __version__; print(__version__)"
