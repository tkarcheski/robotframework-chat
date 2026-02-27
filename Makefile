# robotframework-chat Makefile
# Run `make help` for a list of targets.
#
# Layers (debug bottom-up):
#   Foundation: Robot Framework tests
#   Layer 1:    Python code quality
#   Layer 2:    Docker services
#   Layer 3:    CI pipelines
#   Layer 4:    Release & versioning

COMPOSE  := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || { echo "Error: Docker Compose V2 is required. Install it with: https://docs.docker.com/compose/install/" >&2; echo "false"; })
ROBOT    := uv run robot
LISTENER := --listener rfc.db_listener.DbListener --listener rfc.git_metadata_listener.GitMetaData --listener rfc.ollama_timestamp_listener.OllamaTimestampListener --listener rfc.loki_listener.LokiListener
DRYRUN_LISTENER := --listener rfc.dry_run_listener.DryRunListener

# Load .env if present
-include .env
export

.PHONY: help install \
        robot robot-math robot-docker robot-safety robot-dryrun \
        robot-math-import robot-import import \
        send-results \
        discover-local-nodes discover-local-models run-local-models \
        code-quality-lint code-quality-format code-quality-typecheck \
        code-quality-check code-quality-coverage code-quality-audit \
        docker-up docker-down docker-restart docker-logs bootstrap \
        cache-flush superset-export superset-import \
        ci-generate ci-report ci-deploy run-ci-pipeline \
        opencode-pipeline-review opencode-local-review opencode-audit-markdown \
        ci-release version

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────

install: ## Install Python dependencies
	uv sync --extra dev --extra superset

.env: ## Create .env from .env.example if missing
	cp .env.example .env
	@echo "Created .env from .env.example – edit it if needed."

# ── Foundation: Robot Framework Tests ────────────────────────────────

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
	$(ROBOT) --dryrun --exclude browser -d results/dryrun $(DRYRUN_LISTENER) robot/

import: ## Import results from output.xml files: make import RESULTS_DIR=results/
	uv run python scripts/import_test_results.py $(or $(RESULTS_DIR),results/) -r
	@$(COMPOSE) exec -T redis redis-cli FLUSHALL >/dev/null 2>&1 && \
		echo "Redis cache flushed — Superset will show fresh data." || \
		echo "Note: Redis not running — skip cache flush."

send-results: ## Send results to remote server via rsync (set RESULTS_SERVER_* env vars)
	bash ci/send_results.sh

# ── Local Node Discovery & Model Runs ─────────────────────────────────

discover-local-nodes: ## Scan network for Ollama nodes (online/offline status)
	uv run python scripts/run_local_models.py --discover-nodes

discover-local-models: ## Discover Ollama nodes and list their models
	uv run python scripts/run_local_models.py --discover-models

run-local-models: ## Run test suites against every model on every local node (ITERATIONS=-1 forever, 0 stop-on-error)
	uv run python scripts/run_local_models.py $(if $(ITERATIONS),--iterations $(ITERATIONS),)

# ── Layer 1: Python Code Quality ─────────────────────────────────────

code-quality-lint: ## Run ruff linter
	uv run ruff check .

code-quality-format: ## Auto-format code
	uv run ruff format .

code-quality-typecheck: ## Run mypy type checker
	uv run mypy src/

code-quality-check: code-quality-lint code-quality-typecheck code-quality-coverage ## Run all code quality checks

code-quality-coverage: ## Run pytest with coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html:htmlcov

code-quality-audit: ## Audit dependencies for known vulnerabilities
	uv run pip-audit

# ── Layer 2: Docker Services ─────────────────────────────────────────

docker-up: .env ## Start PostgreSQL + Redis + Superset + Grafana
	$(COMPOSE) up -d

docker-down: ## Stop all services
	$(COMPOSE) down

docker-restart: ## Rebuild images and restart all services
	$(COMPOSE) up -d --build

docker-logs: ## Tail service logs
	$(COMPOSE) logs -f

bootstrap: ## First-time Superset setup (run after 'make docker-up')
	$(COMPOSE) run --rm superset-init

cache-flush: ## Flush Superset/Redis cache (forces dashboards to re-query PostgreSQL)
	@echo "Flushing Redis cache..."
	$(COMPOSE) exec redis redis-cli FLUSHALL
	@echo "Cache flushed — reload Superset dashboards to see fresh data."

superset-export: ## Export Superset dashboards to backups/ directory
	@mkdir -p backups
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(COMPOSE) exec superset superset export-dashboards \
		-f "/tmp/superset_export_$${TIMESTAMP}.zip" && \
	$(COMPOSE) cp "superset:/tmp/superset_export_$${TIMESTAMP}.zip" \
		"./backups/superset_export_$${TIMESTAMP}.zip" && \
	echo "Exported to backups/superset_export_$${TIMESTAMP}.zip"

superset-import: ## Import Superset dashboards from ZIP: make superset-import FILE=backups/export.zip
	$(COMPOSE) cp $(FILE) superset:/tmp/superset_import.zip
	$(COMPOSE) exec superset superset import-dashboards \
		-p /tmp/superset_import.zip \
		-u "$${SUPERSET_ADMIN_USER:-admin}"
	@echo "Dashboard import complete."

# ── Layer 3: CI Pipelines ────────────────────────────────────────────

ci-generate: ## Generate child pipeline YAML (regular|dynamic|discover)
	bash ci/generate.sh $(or $(MODE),regular)

ci-report: ## Generate repo metrics (add POST_MR=1 to post to MR)
	bash ci/report.sh $(if $(POST_MR),--post-mr,)

ci-deploy: ## Deploy Superset to remote host
	bash ci/deploy.sh

run-ci-pipeline: ## Run the full CI pipeline locally (add ROBOT=1 for live robot tests)
	@echo ""
	@echo "============================================"
	@echo "  Local CI Pipeline"
	@echo "============================================"
	@echo ""
	@echo "=== Stage: install ==="
	$(MAKE) install
	@echo ""
	@echo "=== Stage: lint ==="
	bash ci/lint.sh all
	@echo ""
	@echo "=== Stage: test (robot dryrun) ==="
	$(MAKE) robot-dryrun
ifdef ROBOT
	@echo ""
	@echo "=== Stage: test (robot live) ==="
	bash ci/test.sh all
endif
	@echo ""
	@echo "=== Stage: release (dry-run) ==="
	$(MAKE) ci-release
	@echo ""
	@echo "============================================"
	@echo "  Local CI Pipeline: ALL STAGES PASSED"
	@echo "============================================"

opencode-pipeline-review: ## Run OpenCode AI review in CI (pipeline failures + MR diff)
	bash ci/review.sh

opencode-local-review: ## Run OpenCode AI review on local uncommitted/branch changes
	bash ci/local_review.sh

opencode-audit-markdown: ## Audit markdown file references for broken/stale paths (Ollama)
	bash ci/audit_markdown.sh

# ── Layer 4: Release & Versioning ────────────────────────────────────

ci-release: ## Build and verify PyPI package (dry run by default, UPLOAD=1 to publish)
	bash ci/release.sh $(if $(UPLOAD),,--dry-run)

version: ## Print current version
	@uv run python -c "from rfc import __version__; print(__version__)"
