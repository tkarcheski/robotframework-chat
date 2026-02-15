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

# Install pre-commit hooks
pre-commit install
```

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
make test          # Run all test suites (math, docker, safety)
make test-math     # Run math tests
make test-docker   # Run Docker tests
make test-safety   # Run safety tests
make lint          # Run ruff linter
make format        # Auto-format code
make typecheck     # Run mypy type checker
make check         # Run all code quality checks (lint + typecheck)
make import        # Import output.xml results: make import PATH=results/
make version       # Print current version
```

All `make test-*` targets attach both listeners automatically:
- `rfc.db_listener.DbListener` — archives results to database
- `rfc.ci_metadata_listener.CiMetadataListener` — collects CI metadata

### Manual Robot Framework Commands

```bash
# Run with both listeners
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/math/tests/

# Run specific test
uv run robot -d results -t "Test Name" \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/path/tests/file.robot

# Run pre-commit
pre-commit run --all-files

# Check git status
git status
git diff
```

### Docker / Superset

```bash
make up            # Start PostgreSQL + Redis + Superset
make down          # Stop all services
make bootstrap     # First-time Superset setup
make logs          # Tail service logs
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
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/

# Run single test with verbose output
uv run robot -d results -t "Test Name" -L TRACE \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
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
