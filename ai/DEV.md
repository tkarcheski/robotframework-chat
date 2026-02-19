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
# Edit .env with your settings (GitLab, Ollama endpoint, database, etc.)

# Install pre-commit hooks
pre-commit install
```

---

## Environment Configuration

Runtime settings are centralized in `.env` (git-ignored, copied from `.env.example`).

The `.env` file is loaded automatically by:
- **Makefile** — `-include .env` + `export` (all `make` targets see the vars)
- **CI shell scripts** — `set -a; source .env; set +a` (e.g. `ci/sync_db.sh`)
- **pytest** — `python-dotenv` session fixture in `tests/conftest.py` (`override=False`, so `patch.dict` mocks still work)
- **suite_config.py** — `load_config()` overlays env vars (`DEFAULT_MODEL`, `OLLAMA_ENDPOINT`, `GITLAB_API_URL`, `GITLAB_PROJECT_ID`) onto `config/test_suites.yaml`

Key variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | SQLite (`data/test_history.db`) |
| `DEFAULT_MODEL` | LLM model for tests + dashboard | `llama3` |
| `OLLAMA_ENDPOINT` | Ollama API URL | `http://localhost:11434` |
| `OLLAMA_NODES_LIST` | Comma-separated Ollama hostnames | from `config/test_suites.yaml` |
| `GITLAB_API_URL` | GitLab instance URL | (empty) |
| `GITLAB_PROJECT_ID` | Numeric project ID | (empty) |
| `GITLAB_TOKEN` | API token with `read_api` scope | (empty) |

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
make code-lint     # Run ruff linter
make code-format   # Auto-format code
make code-typecheck # Run mypy type checker
make code-check    # Run all code quality checks (lint + typecheck)
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

These must be stored in the database per test run. See `ai/CLAUDE.md` § Inference Parameters.

---

## Resilience Rules (Owner-Confirmed 2026-02-19)

- **Retry infrastructure failures** with backoff (Ollama down, DB unreachable)
- **Emit `WARN`** for transient infra failures, **`FAIL`** only for persistent or LLM failures
- **Distinguish infra failures from model failures** — infra failures don't count against model scores
- **Buffer results locally** if DB is unreachable, sync later
- **Skip remaining tests** for a node that goes offline mid-suite, continue with other nodes

See `ai/CLAUDE.md` § Resilience Rules.

---

## Cross-References

- `ai/CLAUDE.md` — Project intelligence, owner decisions, architecture
- `ai/AGENTS.md` — Agent contract, code style, commands
- `ai/FEATURES.md` — Feature status tracker
- `humans/TODO.md` — Owner action items
- `humans/QA_TRANSCRIPT.md` — Full Q&A record from spec review
