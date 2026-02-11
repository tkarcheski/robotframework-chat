# Development Guide

This document defines how humans and agents develop in this repository.

---

## Philosophy

- Code is a liability until proven correct
- Tests are executable documentation
- Git history is part of the product
- Small changes scale, big commits do not

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

```bash
# Run all tests
uv run pytest
uv run robot -d results robot/math

# Run specific test
uv run robot -d results -t "Test Name" robot/path/tests/file.robot

# Run pre-commit
pre-commit run --all-files

# Check git status
git status
git diff
```

---

## Robot Framework Best Practices

### Syntax Compatibility
- Use `[Return]` (not `RETURN`) for keyword return values
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
uv run robot -d results -L DEBUG robot/path/

# Run single test with verbose output
uv run robot -d results -t "Test Name" -L TRACE robot/path/tests/file.robot

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
