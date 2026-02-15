# robotframework-chat Makefile
# Run `make help` for a list of targets.

COMPOSE  := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || { echo "Error: Docker Compose V2 is required. Install it with: https://docs.docker.com/compose/install/" >&2; echo "false"; })
ROBOT    := uv run robot
LISTENER := --listener rfc.db_listener.DbListener --listener rfc.ci_metadata_listener.CiMetadataListener --listener rfc.ollama_timestamp_listener.OllamaTimestampListener

# Load .env if present
-include .env
export

.PHONY: help install up down restart logs bootstrap \
        test test-math test-docker test-safety \
        import lint format typecheck check version

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────

install: ## Install Python dependencies
	uv sync --extra dev --extra superset

# ── Docker / Superset ─────────────────────────────────────────────────

.env: ## Create .env from .env.example if missing
	cp .env.example .env
	@echo "Created .env from .env.example – edit it if needed."

up: .env ## Start PostgreSQL + Redis + Superset
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

# ── Versioning ────────────────────────────────────────────────────────

version: ## Print current version
	@python -c "from src.rfc import __version__; print(__version__)"
