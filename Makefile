# robotframework-chat Makefile
# Run `make help` for a list of targets.
#
# Layers (debug bottom-up):
#   Foundation: Robot Framework tests
#   Layer 1:    Python code quality
#   Layer 2:    Docker services
#   Layer 3:    CI pipelines
#   Layer 4:    Release & versioning

# Lazy-once: probe runs on first $(COMPOSE) expansion, then caches the result.
COMPOSE = $(if $(_COMPOSE_CACHED),,$(eval _COMPOSE_CACHED := 1)$(eval _COMPOSE_VAL := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || { echo "Error: Docker Compose V2 is required. Install it with: https://docs.docker.com/compose/install/" >&2; echo "false"; })))$(_COMPOSE_VAL)
ROBOT    := uv run robot
VERSION  := $(shell uv run python -c "from rfc import __version__; print(__version__)")
LISTENER := --listener rfc.db_listener.DbListener --listener rfc.git_metadata_listener.GitMetaData --listener rfc.ollama_timestamp_listener.OllamaTimestampListener --listener rfc.chat_log_listener.ChatLogListener --listener rfc.dialog_listener.DialogListener --listener rfc.agentic_harness_listener.AgenticHarnessListener --listener rfc.generative_listener.GenerativeListener
DRYRUN_LISTENER := --listener rfc.dry_run_listener.DryRunListener
# Opt-in Graylog GELF listeners (private modules/graylog submodule). Not in the
# default LISTENER set so a missing submodule never breaks a normal run.
GRAYLOG_LISTENER := --listener robot_graylog_builtin.robot_graylog_builtin --listener robot_graylog_llm.robot_graylog_llm

# Load .env if present
-include .env
export

# Watermark inputs for the results path + output.xml --metadata flags (Issue #350).
# SESSION_ID is fresh per `make` invocation; all suites chained in one invocation share it.
HOSTNAME           := $(shell hostname)
SESSION_ID         := $(shell uv run python -c "from rfc.harness_cli import makefile_session_id; print(makefile_session_id())")
DEFAULT_MODEL_SLUG := $(shell printf '%s' '$(or $(DEFAULT_MODEL),unknown-model)' | tr -c 'A-Za-z0-9._-' '_')
MODEL_HARNESS_SLUG := $(shell printf '%s' '$(or $(MODEL_HARNESS),unknown-harness)' | tr -c 'A-Za-z0-9._-' '_')

# Path layout: results/<rfc_version>/<model_or_harness>/<test_suite>/<hostname>/<session_id>/
# LLM_* macros take a single arg ($1) — the test suite slug.
LLM_RUN_DIR   = results/$(VERSION)/$(DEFAULT_MODEL_SLUG)/$(1)/$(HOSTNAME)/$(SESSION_ID)
AGENT_RUN_DIR = results/$(VERSION)/$(MODEL_HARNESS_SLUG)/$(1)/$(HOSTNAME)/$(SESSION_ID)

META_BASE   = --metadata rfc_version:$(VERSION) --metadata hostname:$(HOSTNAME) --metadata session_id:$(SESSION_ID)
LLM_META    = $(META_BASE) --metadata model_name:$(or $(DEFAULT_MODEL),unknown-model) --metadata test_suite:$(1)
AGENT_META  = $(META_BASE) --metadata model_harness:$(or $(MODEL_HARNESS),unknown-harness) --metadata test_suite:$(1)

VAR_BASE    = --variable SESSION_ID:$(SESSION_ID)
LLM_VARS    = $(VAR_BASE)
AGENT_VARS  = $(VAR_BASE) --variable MODEL_HARNESS:$(or $(MODEL_HARNESS),unknown-harness)

.PHONY: help install update \
        robot robot-math robot-accounting robot-docker robot-safety robot-superset robot-multilingual robot-dryrun \
        robot-review robot-graylog graylog-up graylog-down graylog-logs graylog-demo graylog-doctor \
        robot-bash robot-c robot-rust robot-computer-skills \
        robot robot-math robot-accounting robot-docker robot-safety robot-superset robot-multilingual robot-dryrun \
        robot-swebench robot-openai-evals swebench-discover \
        retry-failed retry-skipped \
        rebot-merge rebot-merge-all \
        discover-local-nodes discover-local-models run-local-models run-all-external \
        robot-autopilot \
        cron-install cron-uninstall cron-sync-models \
        code-quality-lint code-quality-format code-quality-typecheck \
        code-quality-check code-quality-coverage code-quality-audit \
        docker-up docker-down docker-restart docker-logs bootstrap \
        cache-flush sync-metrics superset-sanitize superset-export superset-import superset-diagnose \
        model-cards \
        ci-deploy \
        opencode-audit-markdown \
        build-check docker-build-app docker-test-app version

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────

install: ## Install Python dependencies
	uv sync --extra dev --extra superset --extra swebench

update: ## Fetch, pull latest changes, and sync dependencies (stashes untracked files to avoid conflicts)
	git fetch
	@BEFORE=$$(git stash list | wc -l); \
	git stash --include-untracked || true; \
	AFTER=$$(git stash list | wc -l); \
	STASHED=false; [ "$$AFTER" -gt "$$BEFORE" ] && STASHED=true; \
	if test -f .git/MERGE_HEAD; then \
		echo "ERROR: merge already in progress; resolve it before running make update"; \
		$$STASHED && git stash pop || true; exit 1; \
	fi; \
	if ! git pull; then \
		test -f .git/MERGE_HEAD && git merge --abort; \
		$$STASHED && git stash pop || true; exit 1; \
	fi; \
	$$STASHED && git stash pop || true
	uv sync --extra dev --extra superset --extra swebench

.env: ## Create .env from .env.example if missing
	cp .env.example .env
	@echo "Created .env from .env.example – edit it if needed."

# ── Foundation: Robot Framework Tests ────────────────────────────────
# Pass extra `robot` CLI args via ARGS, e.g.:
#   make robot ARGS="--include agent:claude_code"

robot: robot-math robot-accounting robot-docker robot-safety ## Run all Robot Framework test suites

robot-math: ## Run math tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,math) $(call LLM_META,math) $(LLM_VARS) $(LISTENER) $(ARGS) robot/20__tier2/math/

robot-accounting: ## Run accounting tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,accounting) $(call LLM_META,accounting) $(LLM_VARS) $(LISTENER) $(ARGS) robot/20__tier2/accounting/

robot-docker: ## Run Docker tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,docker) $(call LLM_META,docker) $(LLM_VARS) $(LISTENER) $(ARGS) robot/40__tier4/docker/

robot-safety: ## Run safety tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,safety) $(call LLM_META,safety) $(LLM_VARS) $(LISTENER) $(ARGS) robot/20__tier2/safety/

robot-graylog: ## Run math tests with Graylog GELF listeners (needs `pip install -e ../modules/graylog`)
	GRAYLOG_LLM_ENABLED=1 $(ROBOT) -d $(call LLM_RUN_DIR,graylog) $(call LLM_META,graylog) $(LLM_VARS) $(LISTENER) $(GRAYLOG_LISTENER) $(ARGS) robot/20__tier2/math/

robot-agentic-injection: ## Run agentic prompt injection resistance tests
	$(ROBOT) -d $(call AGENT_RUN_DIR,agentic_injection) $(call AGENT_META,agentic_injection) $(AGENT_VARS) $(LISTENER) $(ARGS) robot/20__tier2/agentic_injection/

robot-agentic-coding: ## Run agentic coding behaviour tests
	$(ROBOT) -d $(call AGENT_RUN_DIR,agentic_coding) $(call AGENT_META,agentic_coding) $(AGENT_VARS) $(LISTENER) $(ARGS) robot/40__tier4/agentic_coding/

robot-agent: robot-agentic-injection robot-agentic-coding ## Master agent test suite (agentic injection + coding)

robot-bash: ## Run bash scripting tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,bash) $(call LLM_META,bash) $(LLM_VARS) $(LISTENER) $(ARGS) robot/40__tier4/docker/bash/

robot-c: ## Run C programming tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,c) $(call LLM_META,c) $(LLM_VARS) $(LISTENER) $(ARGS) robot/40__tier4/docker/c/

robot-rust: ## Run Rust programming tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,rust) $(call LLM_META,rust) $(LLM_VARS) $(LISTENER) $(ARGS) robot/40__tier4/docker/rust/

robot-computer-skills: robot-bash robot-c robot-rust ## Run all computer skills tests

robot-superset: ## Test PostgreSQL connection and push host info to database
	$(ROBOT) -d $(call LLM_RUN_DIR,superset) $(call LLM_META,superset) $(LLM_VARS) $(LISTENER) $(ARGS) robot/20__tier2/superset/

robot-multilingual: ## Run multilingual instruction-following tests (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,multilingual) $(call LLM_META,multilingual) $(LLM_VARS) $(LISTENER) $(ARGS) robot/10__tier1/multilingual/

robot-swebench: ## Run SWE-bench evaluation (Robot Framework)
	$(ROBOT) -d $(call LLM_RUN_DIR,swebench) $(call LLM_META,swebench) $(LLM_VARS) $(LISTENER) $(ARGS) robot/40__tier4/swebench/

robot-openai-evals: ## Run the OpenAI-Evals umbrella suite (scaffolding stub until child suites land — #621)
	$(ROBOT) -d $(call LLM_RUN_DIR,openai-evals) $(call LLM_META,openai-evals) $(LLM_VARS) $(LISTENER) $(ARGS) robot/00__tier0/openai_evals/

swebench-discover: ## List available SWE-bench instances
	uv run python scripts/run_swebench.py --discover

robot-dryrun: ## Validate all Robot tests (dry run, no execution)
	$(ROBOT) --dryrun --exclude browser -d results/$(VERSION)/dryrun $(DRYRUN_LISTENER) $(ARGS) robot/

robot-review: ## Check tag compliance in output.xml (run after robot-dryrun)
	uv run python scripts/robot_review.py

retry-failed: ## Re-run failed tests from results/$(VERSION)/ using --rerunfailed
	@for xml in $$(find results/$(VERSION)/ -name output.xml -not -path '*/combined/*' -not -path '*/dryrun/*'); do \
		out_dir=$$(dirname "$$xml"); \
		suite_name=$$(echo "$$xml" | awk -F/ '{print $$(NF-3)}'); \
		src_dir=$$(ls -d robot/*tier*/$$suite_name/tests robot/*tier*/$$suite_name robot/40__tier4/docker/$$suite_name 2>/dev/null | head -1); \
		if [ -z "$$src_dir" ] || [ ! -d "$$src_dir" ]; then \
			echo "WARNING: cannot resolve source tree for suite '$$suite_name' (xml=$$xml); skipping retry" >&2; \
			continue; \
		fi; \
		echo "==> Retrying failed tests from $$xml (source: $$src_dir)"; \
		$(ROBOT) -d $$out_dir \
			--rerunfailed $$xml \
			$(AGENT_VARS) \
			$(LISTENER) \
			$$src_dir || true; \
	done

retry-skipped: ## Re-run skipped tests from results/$(VERSION)/
	@for xml in $$(find results/$(VERSION)/ -name output.xml -not -path '*/combined/*' -not -path '*/dryrun/*'); do \
		out_dir=$$(dirname "$$xml"); \
		suite_name=$$(echo "$$xml" | awk -F/ '{print $$(NF-3)}'); \
		src_dir=$$(ls -d robot/*tier*/$$suite_name/tests robot/*tier*/$$suite_name robot/40__tier4/docker/$$suite_name 2>/dev/null | head -1); \
		if [ -z "$$src_dir" ] || [ ! -d "$$src_dir" ]; then \
			echo "WARNING: cannot resolve source tree for suite '$$suite_name' (xml=$$xml); skipping retry" >&2; \
			continue; \
		fi; \
		test_args=$$(uv run python -m rfc.rerun_skipped -0 "$$xml"); \
		if [ -n "$$test_args" ]; then \
			echo "==> Retrying skipped tests from $$xml (source: $$src_dir)"; \
			printf '%s' "$$test_args" | xargs -0 \
				$(ROBOT) -d $$out_dir \
				$(AGENT_VARS) \
				$(LISTENER) \
				$$src_dir || true; \
		fi; \
	done

rebot-merge: ## Merge output.xml files: make rebot-merge DIRS="results/1.5.4/math results/1.5.4/docker"
	uv run python -m rfc.rebot_merger $(DIRS)

rebot-merge-all: ## Merge all output.xml in results/$(VERSION)/
	uv run python -m rfc.rebot_merger results/$(VERSION)/

# ── Local Node Discovery & Model Runs ─────────────────────────────────

discover-local-nodes: ## Scan network for Ollama nodes (online/offline status)
	uv run python scripts/run_local_models.py --mode external --discover-nodes

discover-local-models: ## Discover Ollama nodes and list their models
	uv run python scripts/run_local_models.py --mode external --discover-models

run-local-models: ## Run suites against curated hosts from host-config.toml with loaded-model priority (AUDIT=0 to skip audit, ITERATIONS=-1 forever, 0 stop-on-error)
	uv run python scripts/run_local_models.py --mode toml $(if $(ITERATIONS),--iterations $(ITERATIONS),) $(if $(filter 0,$(AUDIT)),--no-audit,)

run-all-external: ## Legacy wide-net run: env-var/subnet discovery, runs everything found (AUDIT=0, ITERATIONS as above)
	uv run python scripts/run_local_models.py --mode external $(if $(ITERATIONS),--iterations $(ITERATIONS),) $(if $(filter 0,$(AUDIT)),--no-audit,)

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

# ── Graylog stack (GELF sink for the private graylog module) ─────────
# Layout-agnostic (#632 review): the graylog ops dir lives at
# ../modules/ops/graylog in the monorepo and is absent on the public mirror.
# Resolve at expansion time; targets skip-and-log when the module isn't here.
GRAYLOG_DIR := $(firstword $(wildcard ../modules/ops/graylog) $(wildcard graylog))
GRAYLOG_COMPOSE = docker compose -p rfc-graylog -f $(GRAYLOG_DIR)/docker-compose.yml
GRAYLOG_GUARD = @test -n "$(GRAYLOG_DIR)" || { echo "graylog module not present (private module; monorepo only) — skipping"; exit 0; }

graylog-up: ## Start Graylog (MongoDB+OpenSearch+Graylog) and auto-provision GELF inputs
	$(GRAYLOG_GUARD)
	@test -z "$(GRAYLOG_DIR)" || { $(GRAYLOG_COMPOSE) up -d && echo "Graylog UI: http://localhost:$${GRAYLOG_WEB_PORT:-9000}  (admin/admin)"; }

graylog-down: ## Stop the Graylog stack
	$(GRAYLOG_GUARD)
	@test -z "$(GRAYLOG_DIR)" || $(GRAYLOG_COMPOSE) down

graylog-logs: ## Tail Graylog stack logs
	$(GRAYLOG_GUARD)
	@test -z "$(GRAYLOG_DIR)" || $(GRAYLOG_COMPOSE) logs -f

graylog-demo: ## Send real harness LLM events into a running Graylog (needs graylog-up + Ollama)
	$(GRAYLOG_GUARD)
	@test -z "$(GRAYLOG_DIR)" || GRAYLOG_LLM_ENABLED=1 uv run python $(GRAYLOG_DIR)/demo_emit.py

graylog-doctor: ## Diagnose why Robot logs aren't reaching Graylog (submodule/install/inputs/env)
	$(GRAYLOG_GUARD)
	@test -z "$(GRAYLOG_DIR)" || uv run python $(GRAYLOG_DIR)/doctor.py

bootstrap: ## First-time Superset setup (run after 'make docker-up')
	$(COMPOSE) run --rm superset-init

cache-flush: ## Flush caches and refresh all dashboards (Superset + RF Metrics)
	@echo "Flushing Redis cache..."
	$(COMPOSE) exec redis redis-cli FLUSHALL
	@echo "Triggering RF Metrics dashboard regeneration..."
	$(COMPOSE) restart metrics
	@echo "Done — Superset will re-query on next load; RF Metrics are regenerating now."

sync-metrics: ## Trigger immediate RF Metrics dashboard regeneration from output.xml files
	@echo "Syncing output.xml files to RF Metrics dashboard..."
	$(COMPOSE) exec -T metrics /bin/bash -c 'source /app/entrypoint.sh && generate_metrics'
	@echo "Metrics sync complete — view at http://localhost:$${METRICS_PORT:-8089}"

superset-sanitize: ## Truncate all RFC data tables (preserves dashboards/charts)
	uv run python scripts/sanitize_superset_db.py

superset-export: ## Export Superset dashboards + DB dump to backups/, then commit + push to the backups repo (main)
	@mkdir -p backups
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(COMPOSE) exec superset superset export-dashboards \
		-f "/tmp/superset_export_$${TIMESTAMP}.zip" && \
	$(COMPOSE) cp "superset:/tmp/superset_export_$${TIMESTAMP}.zip" \
		"./backups/superset_export_$${TIMESTAMP}.zip" && \
	echo "Exported dashboards to backups/superset_export_$${TIMESTAMP}.zip"; \
	echo "Dumping PostgreSQL ($(or $(POSTGRES_DB),rfc)) to backups/db_$${TIMESTAMP}.sql.gz..."; \
	if $(COMPOSE) exec -T postgres pg_dump -U "$(or $(POSTGRES_USER),rfc)" "$(or $(POSTGRES_DB),rfc)" \
		> "backups/db_$${TIMESTAMP}.sql"; then \
		gzip -f "backups/db_$${TIMESTAMP}.sql" \
			&& echo "Dumped DB to backups/db_$${TIMESTAMP}.sql.gz"; \
	else \
		echo "WARNING: pg_dump failed — skipping DB dump"; \
		rm -f "backups/db_$${TIMESTAMP}.sql" "backups/db_$${TIMESTAMP}.sql.gz"; \
	fi; \
	bash ci/backup_push.sh "chore: backup $${TIMESTAMP}"

superset-diagnose: ## Diagnose Superset database connectivity and data pipeline
	uv run python scripts/diagnose_superset_db.py

superset-import: ## Import Superset dashboards from ZIP: make superset-import FILE=backups/export.zip
	$(COMPOSE) cp $(FILE) superset:/tmp/superset_import.zip
	$(COMPOSE) exec superset superset import-dashboards \
		-p /tmp/superset_import.zip \
		-u "$${SUPERSET_ADMIN_USER:-admin}"
	@echo "Dashboard import complete."

model-cards: ## Generate Markdown model cards from test results (requires Superset DB)
	uv run python -m rfc.make_model_cards

# ── Layer 3: CI Pipelines ────────────────────────────────────────────

ci-deploy: ## Deploy Superset to remote host
	bash ci/deploy.sh

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
