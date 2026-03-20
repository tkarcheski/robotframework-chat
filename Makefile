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
LISTENER := --listener rfc.db_listener.DbListener --listener rfc.git_metadata_listener.GitMetaData --listener rfc.ollama_timestamp_listener.OllamaTimestampListener --listener rfc.chat_log_listener.ChatLogListener
DRYRUN_LISTENER := --listener rfc.dry_run_listener.DryRunListener

# Load .env if present
-include .env
export

.PHONY: help install update \
        robot robot-math robot-accounting robot-docker robot-safety robot-superset robot-dryrun \
        robot-bash robot-c robot-rust robot-computer-skills \
        robot robot-math robot-accounting robot-docker robot-safety robot-superset robot-dryrun \
        send-results \
        rebot-merge rebot-merge-all \
        discover-local-nodes discover-local-models run-local-models \
        robot-autopilot \
        cron-install cron-uninstall cron-sync-models \
        code-quality-lint code-quality-format code-quality-typecheck \
        code-quality-check code-quality-coverage code-quality-audit \
        docker-up docker-down docker-restart docker-logs bootstrap \
        cache-flush superset-sanitize superset-export superset-import superset-diagnose \
        ci-generate ci-report ci-deploy \
        opencode-pipeline-review opencode-local-review opencode-audit-markdown \
        build-check docker-build-app docker-test-app version

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────

install: ## Install Python dependencies
	uv sync --extra dev --extra superset

update: ## Fetch, pull latest changes, and sync dependencies
	git fetch
	git pull
	uv sync --extra dev --extra superset

.env: ## Create .env from .env.example if missing
	cp .env.example .env
	@echo "Created .env from .env.example – edit it if needed."

# ── Foundation: Robot Framework Tests ────────────────────────────────

robot: robot-math robot-accounting robot-docker robot-safety ## Run all Robot Framework test suites

robot-math: ## Run math tests (Robot Framework)
	$(ROBOT) -d results/math $(LISTENER) robot/math/tests/

robot-accounting: ## Run accounting tests (Robot Framework)
	$(ROBOT) -d results/accounting $(LISTENER) robot/accounting/tests/

robot-docker: ## Run Docker tests (Robot Framework)
	$(ROBOT) -d results/docker $(LISTENER) robot/docker/

robot-safety: ## Run safety tests (Robot Framework)
	$(ROBOT) -d results/safety $(LISTENER) robot/safety/

robot-bash: ## Run bash scripting tests (Robot Framework)
	$(ROBOT) -d results/bash $(LISTENER) robot/docker/bash/

robot-c: ## Run C programming tests (Robot Framework)
	$(ROBOT) -d results/c $(LISTENER) robot/docker/c/

robot-rust: ## Run Rust programming tests (Robot Framework)
	$(ROBOT) -d results/rust $(LISTENER) robot/docker/rust/

robot-computer-skills: robot-bash robot-c robot-rust ## Run all computer skills tests

robot-superset: ## Test PostgreSQL connection and push host info to database
	$(ROBOT) -d results/superset $(LISTENER) robot/superset/tests/

robot-dryrun: ## Validate all Robot tests (dry run, no execution)
	$(ROBOT) --dryrun --exclude browser -d results/dryrun $(DRYRUN_LISTENER) robot/

send-results: ## Send results to remote server via rsync (set RESULTS_SERVER_* env vars)
	bash ci/send_results.sh

rebot-merge: ## Merge output.xml files: make rebot-merge DIRS="results/math results/docker"
	uv run python -m rfc.rebot_merger $(DIRS)

rebot-merge-all: ## Merge all output.xml in results/
	uv run python -m rfc.rebot_merger results/

# ── Local Node Discovery & Model Runs ─────────────────────────────────

discover-local-nodes: ## Scan network for Ollama nodes (online/offline status)
	uv run python scripts/run_local_models.py --discover-nodes

discover-local-models: ## Discover Ollama nodes and list their models
	uv run python scripts/run_local_models.py --discover-models

run-local-models: ## Run test suites against every model on every local node (ITERATIONS=-1 forever, 0 stop-on-error)
	uv run python scripts/run_local_models.py $(if $(ITERATIONS),--iterations $(ITERATIONS),)

robot-autopilot: ## Poll for git updates → update + install + run-local-models; idle 6h → re-run
	@scripts/robot_autopilot.sh

cron-install: ## Install hourly cron job for update + sync-models + run-local-models
	@scripts/cron_run_local_models.sh --install

cron-uninstall: ## Remove hourly cron job
	@scripts/cron_run_local_models.sh --uninstall

cron-sync-models: ## Pull any master models missing from local Ollama
	@scripts/cron_run_local_models.sh --sync-models

# ── Layer 1: Python Code Quality ─────────────────────────────────────

code-quality-lint: ## Run ruff linter
	uv run ruff check .

code-quality-format: ## Auto-format code
	uv run ruff format .

code-quality-typecheck: ## Run mypy type checker
	MYPYPATH=src uv run mypy --explicit-package-bases -p rfc

code-quality-check: code-quality-lint code-quality-typecheck code-quality-coverage ## Run all code quality checks

code-quality-coverage: ## Run pytest with coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html:htmlcov

code-quality-audit: ## Audit dependencies for known vulnerabilities
	uv run pip-audit

# ── Layer 2: Docker Services ─────────────────────────────────────────

docker-up: .env ## Start the full stack (app + PostgreSQL + Redis + Superset + Metrics)
	$(COMPOSE) up -d

docker-down: ## Stop all services
	$(COMPOSE) down

docker-restart: ## Rebuild images and restart all services
	$(COMPOSE) up -d --build

docker-logs: ## Tail service logs
	$(COMPOSE) logs -f

bootstrap: ## First-time Superset setup (run after 'make docker-up')
	$(COMPOSE) run --rm superset-init

cache-flush: ## Flush caches and refresh all dashboards (Superset + RF Metrics)
	@echo "Flushing Redis cache..."
	$(COMPOSE) exec redis redis-cli FLUSHALL
	@echo "Triggering RF Metrics dashboard regeneration..."
	$(COMPOSE) restart metrics
	@echo "Done — Superset will re-query on next load; RF Metrics are regenerating now."

superset-sanitize: ## Truncate all RFC data tables (preserves dashboards/charts)
	uv run python scripts/sanitize_superset_db.py

superset-export: ## Export Superset dashboards to backups/ directory
	@mkdir -p backups
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(COMPOSE) exec superset superset export-dashboards \
		-f "/tmp/superset_export_$${TIMESTAMP}.zip" && \
	$(COMPOSE) cp "superset:/tmp/superset_export_$${TIMESTAMP}.zip" \
		"./backups/superset_export_$${TIMESTAMP}.zip" && \
	echo "Exported to backups/superset_export_$${TIMESTAMP}.zip"

superset-diagnose: ## Diagnose Superset database connectivity and data pipeline
	uv run python scripts/diagnose_superset_db.py

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

opencode-pipeline-review: ## Run OpenCode AI review in CI (pipeline failures + MR diff)
	bash ci/review.sh

opencode-local-review: ## Run OpenCode AI review on local uncommitted/branch changes
	bash ci/local_review.sh

opencode-audit-markdown: ## Audit markdown file references for broken/stale paths (Ollama)
	bash ci/audit_markdown.sh

# ── Layer 4: Release & Versioning ────────────────────────────────────
# Publishing is handled by GitHub Actions trusted publishing.
# See .github/workflows/pypi-publish.yml

build-check: ## Build and verify PyPI package locally (no upload)
	bash ci/release.sh

docker-build-app: ## Build the application Docker image locally
	docker build -t ghcr.io/tkarcheski/robotframework-chat:local .

docker-test-app: docker-build-app ## Smoke-test the application Docker image (dry-run)
	docker run --rm ghcr.io/tkarcheski/robotframework-chat:local \
		make robot-dryrun

version: ## Print current version
	@uv run python -c "from rfc import __version__; print(__version__)"
