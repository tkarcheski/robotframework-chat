# Refactoring & Maintenance Guide

Instructions for maintaining robotframework-chat following software engineering
best practices. This document is intended for both human developers and AI agents
performing code reviews or automated refactoring.

---

## Principles

1. **Leave the codebase better than you found it** -- but only within the scope
   of the current change. Drive-by cleanups belong in separate commits.

2. **Refactor under green tests.** Never restructure code that lacks test
   coverage. Write tests first, then refactor.

3. **Prefer deletion over abstraction.** Dead code, unused imports, and
   commented-out blocks should be removed, not hidden behind flags.

4. **Small, reversible changes.** Each refactoring commit should be safe to
   revert independently without breaking other work.

5. **Names are documentation.** Rename unclear variables, functions, and modules
   before adding comments. If the name is right, the comment is unnecessary.

---

## When to Refactor

Refactor when you observe any of the following:

| Signal | Action |
|--------|--------|
| Duplicated logic across files | Extract shared function into appropriate module |
| Function exceeds ~50 lines | Split into smaller, testable units |
| Module exceeds ~500 lines | Consider splitting by responsibility |
| Inconsistent naming | Align with project conventions (see AGENTS.md) |
| Unused imports or variables | Remove them |
| Deeply nested conditionals | Flatten with early returns or guard clauses |
| Hard-coded values used in multiple places | Promote to constants or config |
| Type errors reported by mypy | Fix the types, don't add `# type: ignore` |
| Test flakiness | Stabilize the test before adding new features |

Do **not** refactor:

- During a feature implementation (finish the feature first)
- Without running `pre-commit run --all-files` afterward
- Code you don't understand yet (read it first, write a test, then change it)

---

## Refactoring Workflow

```
1. Identify the target
2. Ensure test coverage exists (write tests if not)
3. Run full test suite -- confirm green
4. Make the structural change
5. Run full test suite -- confirm still green
6. Run pre-commit hooks
7. Commit with type prefix: refactor: <summary>
8. Repeat for the next target
```

Never combine a refactor commit with a feature or bug fix commit.

---

## Code Health Checklist

Use this checklist during code reviews and periodic maintenance:

### Python (`src/rfc/`)

- [ ] All public functions have type annotations
- [ ] No bare `except:` clauses -- catch specific exceptions
- [ ] Imports follow ordering: stdlib, third-party, local
- [ ] No circular imports between modules
- [ ] Dataclasses or named tuples used instead of raw dicts for structured data
- [ ] `from __future__ import annotations` not needed (Python 3.11+)
- [ ] No mutable default arguments (`def f(x=[])` -- use `None` sentinel)
- [ ] Context managers used for resource cleanup (files, connections, containers)
- [ ] Logging uses `robot.api.logger` in keyword code, `logging` in standalone scripts
- [ ] Error messages include enough context to diagnose the problem

### Robot Framework (`robot/`)

- [ ] `RETURN` used instead of deprecated `[Return]`
- [ ] Each test has `[Documentation]` and `[Tags]`
- [ ] Suite-level `Setup` / `Teardown` handles container lifecycle
- [ ] No hardcoded ports -- use `Find Available Port`
- [ ] Resource files don't duplicate keywords from other resource files
- [ ] Variables use correct sigil: `${scalar}`, `@{list}`, `&{dict}`

### Repository-Wide

- [ ] No secrets, tokens, or credentials in tracked files
- [ ] `.env.example` reflects all required environment variables
- [ ] `pyproject.toml` extras match actual usage groups
- [ ] `uv.lock` is up to date with `pyproject.toml`
- [ ] Pre-commit hooks pass on all files
- [ ] `ruff check` and `mypy` report zero errors
- [ ] All Makefile targets documented in `make help`

---

## Dependency Maintenance

### Updating Dependencies

```bash
# Update all dependencies
uv lock --upgrade

# Update a specific package
uv lock --upgrade-package <package-name>

# Verify nothing broke
make check
make test
```

### Dependency Hygiene Rules

1. Pin exact versions only in `uv.lock` -- use ranges in `pyproject.toml`
2. Audit new dependencies before adding them:
   - Is it actively maintained?
   - Does it have a permissive license?
   - Can the same result be achieved with stdlib?
3. Remove unused dependencies promptly -- they increase attack surface and
   install time
4. Keep `--extra dev` dependencies separate from runtime dependencies

---

## Structural Guidelines

### Module Responsibilities

| Module | Single Responsibility |
|--------|----------------------|
| `keywords.py` | Robot Framework keyword bridge for LLM operations |
| `ollama.py` | HTTP client for Ollama API -- no Robot Framework awareness |
| `grader.py` | Answer evaluation logic -- pure functions where possible |
| `models.py` | Shared data structures (dataclasses) |
| `db_listener.py` | Write test results to SQL -- no business logic |
| `test_database.py` | Database connection and schema management |
| `container_manager.py` | Docker lifecycle -- create, exec, stop, remove |
| `docker_keywords.py` | Robot Framework keyword bridge for Docker operations |

If a module starts doing two things, split it.

### Adding New Test Suites

1. Create directory: `robot/<suite-name>/tests/`
2. Add resource file if needed: `robot/<suite-name>/resources/`
3. Register in `config/test_suites.yaml`
4. Add Makefile target: `test-<suite-name>`
5. Run pipeline generation locally to validate:
   ```bash
   uv run python scripts/generate_pipeline.py --mode regular -o /dev/stdout
   ```

### Adding New Listeners

1. Create listener in `src/rfc/` following the Robot Framework listener API v3
2. Add to the listener table in `ai/AGENTS.md`
3. Add `--listener` flag to all Makefile `test-*` targets
4. Update `scripts/generate_pipeline.py` to include the listener in CI jobs

---

## Technical Debt Tracking

When you encounter technical debt during a review but it's out of scope for the
current change:

1. Do **not** fix it in the current PR -- scope creep causes review fatigue
2. Create a follow-up issue or add a `TODO(#issue)` comment with a tracking reference
3. If the debt is severe enough to block the current change, flag it in the review

### Common Debt Patterns in This Repo

| Pattern | Resolution |
|---------|-----------|
| Duplicated listener attachment flags | Centralize in a shared config or Makefile variable |
| Magic strings for model names | Use constants or config file lookups |
| Mixed sync/async patterns | Standardize on one approach per module |
| Test setup duplication | Extract shared fixtures to resource files |

---

## Review Standards

When reviewing code (whether as a human or an AI agent):

### Must Fix (block merge)

- Broken tests
- Security vulnerabilities (credential exposure, injection, path traversal)
- Data loss potential
- API contract violations
- Missing error handling at system boundaries (user input, HTTP responses)

### Should Fix (request changes)

- Missing type annotations on public functions
- Unclear naming
- Duplicated logic
- Missing test coverage for new behavior
- Overly broad exception handling

### Consider (comment, don't block)

- Minor style inconsistencies already covered by ruff
- Alternative algorithm choices with similar complexity
- Documentation improvements for existing code

### Review Checklist for PRs

- [ ] Tests pass (`make test`)
- [ ] Pre-commit passes (`pre-commit run --all-files`)
- [ ] Types check (`make typecheck`)
- [ ] No unrelated changes bundled in
- [ ] Commit messages follow `<type>: <summary>` format
- [ ] New behavior has corresponding tests
- [ ] No TODOs without issue references
- [ ] Config changes reflected in `.env.example` if applicable

---

## Performance Considerations

- **Robot Framework tests** are I/O-bound (LLM API calls, Docker operations).
  Optimize by reducing unnecessary container restarts and API round-trips,
  not by micro-optimizing Python code.
- **Database writes** should be batched where possible. The `DbListener` already
  handles this at the suite level.
- **Docker containers** are expensive to create and destroy. Prefer suite-level
  setup/teardown over test-level when tests share the same container config.
- **CI pipeline time** is dominated by model inference. Keep the regular pipeline
  on the smallest viable model to preserve fast feedback loops.
