# Development Guide

This document defines how humans and agents develop in this repository.

---

## Philosophy

- Code is a liability until proven correct
- Tests are executable documentation
- Git history is part of the product
- Small changes scale, big commits do not

---

## Setup

```bash
# Install all dependencies
make install
# or: uv sync --extra dev --extra superset

# Create environment config from template
cp .env.example .env
# Edit .env with your settings (Ollama endpoint, database, etc.)

# Install pre-commit hooks
pre-commit install
```

### Docker host prerequisites

Redis (the Superset cache in `docker-compose.yml`) warns at startup unless
memory overcommit is enabled on the **host** — a sysctl, not fixable inside
the container. Without it, BGSAVE forks can fail under memory pressure
(issue #415; low severity here since Redis is cache-only):

```bash
sudo sysctl vm.overcommit_memory=1                     # immediate
echo 'vm.overcommit_memory = 1' | sudo tee -a /etc/sysctl.conf  # persistent
```

---

## Environment Configuration

Runtime settings are centralized in `.env` (git-ignored, copied from `.env.example`).

The `.env` file is loaded automatically by:
- **Makefile** — `-include .env` + `export` (all `make` targets see the vars)
- **CI shell scripts** — `set -a; source .env; set +a` (e.g. `ci/lint.sh`)
- **pytest** — `python-dotenv` session fixture in `tests/conftest.py` (`override=False`, so `patch.dict` mocks still work)
- **suite_config.py** — `load_config()` overlays env vars (`DEFAULT_MODEL`, `OLLAMA_ENDPOINT`) onto `config/test_suites.yaml`

### Core Variables

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `.env` fallback | db_listener, test_database, dry_run_listener |
| `DATABASE_HOST` | Hostname for DB (CI builds `DATABASE_URL` from this) | `localhost` | CI workflows |
| `DEFAULT_MODEL` | LLM model for tests | `gpt-oss:20b` (CI: `qwen3.5:27b`) | ollama.py, keywords, listeners, scripts |
| `OLLAMA_ENDPOINT` | Ollama API URL | `http://localhost:11434` | ollama.py, pre_run_modifier, listeners |
| `OLLAMA_TIMEOUT` | Request timeout in seconds | `5400` (90 min) | ollama.py, keywords, safety_keywords, Robot resources |

### Node Discovery

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `OLLAMA_NODES_LIST` | Comma-separated hostnames | from `config/test_suites.yaml` | discover_nodes.py, run_local_models.py (`--mode external`) |
| `OLLAMA_NODES` | Legacy: comma-separated `host:port` entries | (empty) | discover_ollama.py |
| `OLLAMA_SUBNET` | CIDR notation for subnet scanning | (empty) | discover_ollama.py |
| `RFC_HOSTNAME` | Override hostname in test results | `platform.node()` | host_info.py |

#### host-config.toml vs env-var discovery (issue #306)

`make run-local-models` no longer uses the env vars above. It reads a
curated host inventory from `host-config.toml` at the repo root
(git-ignored; `cp host-config.toml.example host-config.toml`). The runner
builds a global `(model, suite)` job queue and dispatches it across hosts
(`rfc.host_scheduler`), preferring jobs whose model is already loaded in
VRAM per Ollama `/api/ps` — this skips cold model loads (10–60s on large
models). Per-host knobs: `priority`, `max_parallel`, `skip_models`; global
knobs: `connect_timeout`, `request_timeout`, `global_max_parallel`.

**Migration:** each hostname in your old `OLLAMA_NODES_LIST` becomes a
`[[hosts]]` entry with `endpoint = "http://<host>:11434"`. The old
env-var/subnet behavior lives on as `make run-all-external` (sequential
by default; `execution.parallel` in `config/local_models.yaml` is its
global concurrency cap and is deprecated for the TOML path in favor of
`global_max_parallel`).

### PostgreSQL & Superset

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `POSTGRES_USER` | Database user | `rfc` | docker-compose.yml, superset_config.py |
| `POSTGRES_PASSWORD` | Database password | `changeme` | docker-compose.yml, superset_config.py |
| `POSTGRES_DB` | Database name | `rfc` | docker-compose.yml, superset_config.py |
| `POSTGRES_PORT` | Exposed host port | `5433` | docker-compose.yml |
| `POSTGRES_INTERNAL_PORT` | Container-internal PG port | `5432` | docker-compose.yml, superset_config.py |
| `SUPERSET_SECRET_KEY` | Flask secret key | (must generate) | docker-compose.yml |
| `SUPERSET_PORT` | Web UI port | `8088` | docker-compose.yml |
| `SUPERSET_ADMIN_USER` | Initial admin username | `admin` | docker-compose.yml |
| `SUPERSET_ADMIN_PASSWORD` | Initial admin password | `changeme` | docker-compose.yml |
| `SUPERSET_ADMIN_EMAIL` | Initial admin email | `admin@rfc.local` | docker-compose.yml |

### Hugging Face

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `HF_TOKEN` | API token (read-only access is sufficient) | (empty) | scripts/import_hf_dataset.py, huggingface_keywords, `datasets` lib |

### AI Code Review

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `AUDIT_MODEL` | Model for markdown audit | `ollama/qwen3-coder:30b-a3b-q4_K_M` | ci/audit_markdown.sh |
| `BASE_BRANCH` | Base branch for diff reviews | auto-detected (main/master) | ci/audit_markdown.sh |
| `COMMIT_DEPTH` | Recent commits for markdown audit | `20` | ci/audit_markdown.sh |

### CI/Deploy (only needed in CI environments)

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `SUPERSET_DEPLOY_HOST` | Remote deploy target hostname | (required) | ci/deploy.sh |
| `SUPERSET_DEPLOY_USER` | SSH user for deploy | (required) | ci/deploy.sh |
| `SUPERSET_DEPLOY_PATH` | Remote path for deploy | (required) | ci/deploy.sh |

### Auto-Set CI Variables (do not configure in `.env`)

These are set automatically by GitHub Actions:

| Variable | Source | Purpose |
|----------|--------|---------|
| `CI`, `GITHUB_ACTIONS` | CI runner | Platform detection |
| `GITHUB_SHA` | CI runner | Commit hash |
| `GITHUB_REF_NAME` | CI runner | Branch name |
| `GITHUB_RUN_ID`, `GITHUB_RUN_NUMBER`, `GITHUB_JOB` | GitHub Actions | Job/run tracking |
| `GITHUB_EVENT_NUMBER`, `GITHUB_EVENT_NAME` | GitHub Actions | PR / event identification |
| `ROBOT_OUTPUT_DIR` | Robot Framework | Output directory |
| `GITHUB_SERVER_URL`, `GITHUB_REPOSITORY` | GitHub Actions | Repo identification |
| `GITHUB_WORKSPACE` | GitHub Actions | Workspace path |
| `GITHUB_ACTOR` | GitHub Actions | Triggering user |

---

## Test-Driven Development

All behavior changes MUST follow TDD:

1. Write a failing test that describes the desired behavior
2. Run tests and observe failure
3. Implement the minimal solution
4. Run tests and observe success
5. Refactor only after green tests

If a change has no test, it is incomplete.

### Docker Testing Workflow

When working with Docker-based tests:

1. **Always use dynamic port allocation** - Never hardcode ports:
   ```robot
   ${port}=    Docker.Find Available Port    11434    11500
   ```

2. **Clean up containers** - Use unique names and proper teardown:
   ```robot
   Suite Teardown    Run Keyword And Ignore Error    Docker.Stop Container By Name    ${CONTAINER_NAME}
   ```

3. **Handle port conflicts gracefully** - Tests should work even if local services are running

---

## Commit Discipline

Commits should be:

- Small
- Atomic
- Easy to review
- Easy to revert

### One Commit = One Idea

**Good:**
- Add parser
- Fix boundary condition
- Refactor function

**Bad:**
- Parser + refactor + formatting
- Feature + test cleanup
- "Misc fixes"

---

## pre-commit

This repository uses `pre-commit` as a hard gate.

Before committing, always run:

```bash
pre-commit run --all-files
```

Do not commit if hooks fail. Fix the issues first.

---

## Commands

### Makefile Targets (preferred)

```bash
make robot         # Run all Robot Framework test suites
make robot-math    # Run math tests
make robot-docker  # Run Docker tests
make robot-safety  # Run safety tests
make code-quality-check    # Run all code quality checks (lint + typecheck + coverage)
make import        # Import output.xml results: make import PATH=results/
make version       # Print current version
```

All `make robot-*` targets attach both listeners automatically:
- `rfc.db_listener.DbListener` — archives results to database
- `rfc.git_metadata_listener.GitMetaData` — collects CI metadata

### Manual Robot Framework Commands

```bash
# Run with both listeners
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.git_metadata_listener.GitMetaData \
  robot/math/tests/

# Run specific test
uv run robot -d results -t "Test Name" \
  --listener rfc.db_listener.DbListener \
  --listener rfc.git_metadata_listener.GitMetaData \
  robot/path/tests/file.robot

# Run pre-commit
pre-commit run --all-files

# Check git status
git status
git diff
```

### Docker / Superset

```bash
make docker-up     # Start PostgreSQL + Redis + Superset
make docker-down   # Stop all services
make bootstrap     # First-time Superset setup
make docker-logs   # Tail service logs
```

---

## Robot Framework Best Practices

### Syntax Compatibility
- Use `RETURN` (not `[Return]`) for keyword return values
- Keywords must be defined in `*** Keywords ***` section BEFORE test cases
- Use `Run Keyword And Ignore Error` for cleanup operations
- Global variables for cross-suite state: `Set Global Variable`

### Common Pitfalls
1. **Duplicate keyword names** - Ensure unique names across resource files
2. **Port conflicts** - Always use `Find Available Port` for network services
3. **Container cleanup** - Containers may persist after failed tests; use `Stop Container By Name`
4. **API endpoint duplication** - Don't append paths twice (e.g., `/api/generate`)

### Debugging Tips
```bash
# Run with debug output
uv run robot -d results -L DEBUG \
  --listener rfc.db_listener.DbListener \
  --listener rfc.git_metadata_listener.GitMetaData \
  robot/

# Run single test with verbose output
uv run robot -d results -t "Test Name" -L TRACE \
  --listener rfc.db_listener.DbListener \
  --listener rfc.git_metadata_listener.GitMetaData \
  robot/path/tests/file.robot

# Check container logs
docker logs ${CONTAINER_ID}
```

---

## Definition of Done

- [ ] Test written and failing (red)
- [ ] Implementation complete (green)
- [ ] Refactoring done (if needed)
- [ ] pre-commit passes
- [ ] Commit message follows format: `<type>: <summary>`
- [ ] No TODOs or placeholders remain
- [ ] Docker containers properly cleaned up (if applicable)
- [ ] Tests tagged with appropriate grading tier (`tier:0` through `tier:6`)

---

## Inference Parameters (Owner-Confirmed 2026-02-19)

When calling Ollama's `/api/generate`, always specify and record:
- `temperature` — default `0` for benchmarking (deterministic)
- `seed` — fixed seed for reproducibility
- `top_p` — include for completeness
- `top_k` — include for completeness

These must be stored in the database per test run.

---

## Resilience Rules (Owner-Confirmed 2026-02-19)

- **Retry infrastructure failures** with backoff (Ollama down, DB unreachable)
- **Emit `WARN`** for transient infra failures, **`FAIL`** only for persistent or LLM failures
- **Distinguish infra failures from model failures** — infra failures don't count against model scores
- **Buffer results locally** if DB is unreachable, sync later
- **Skip remaining tests** for a node that goes offline mid-suite, continue with other nodes


---

## Cross-References

- `ai/testing.md` — Grading tiers and test rules
- `ai/agents.md` — Agent contract, code style, commands
- `docs/requirements.md` — Project requirements and status tracker
- `humans/TODO.md` — Owner action items
