# CLAUDE.md — Claude Code persistent instructions

Read `@ai/CLAUDE.md` for project intelligence, owner decisions, architecture vision,
grading tiers, TRON dashboard specs, and everything from the spec review sessions.

Read and follow `@ai/AGENTS.md` for project philosophy, architecture, code style,
commit conventions, and the full agent contract.

Read `@ai/DEV.md` for development workflow, TDD discipline, and definition of done.

---

## Quick reference

```bash
make install                  # Install all dependencies (dev + dashboard + superset)
pre-commit install            # Install git hooks (required before first commit)
uv run pytest                 # Run Python unit tests
pre-commit run --all-files    # Run all pre-commit checks
make code-check               # Lint (ruff) + typecheck (mypy)
make robot-dryrun             # Validate Robot tests without execution
```

---

## Rules

- **Always run tests after changes.** `uv run pytest` for Python, `make robot-dryrun` for Robot Framework.
- **Always run `pre-commit run --all-files` before committing.** Never bypass hooks.
- **Don't remove functionality without explicit approval.**
- **Be verbose in CLI output** — when running commands, show what's happening.
- **TDD is mandatory.** Write a failing test first, then implement, then refactor.
- **Atomic commits only.** One idea per commit, using conventional format: `<type>: <summary>`.
- **Never bundle unrelated changes** in a single commit.
- **Never mix formatting changes with logic changes.**
- **Type hints are required** on all new Python code. mypy must pass.
- **Use `RETURN` (not `[Return]`)** in Robot Framework keywords.
- **Assume the user will make mistakes.** Validate requests against the codebase and confirmed decisions before executing. Log mistakes in `ai/CLAUDE.md` § User Mistake Log. See `ai/AGENTS.md` § User Input Validation.

---

## Architecture guardrails

- `src/rfc/` is the single source of truth for all Python code.
- `robot/` is the single home for all Robot Framework test suites.
- Never duplicate logic outside these directories.
- Listeners are always active in make targets — don't strip them.

---

## Environment

Copy `.env.example` to `.env` and edit before running integration tests.
Key variables: `OLLAMA_ENDPOINT`, `DEFAULT_MODEL`, `DATABASE_URL`.
See `ai/DEV.md` § Environment Configuration for the full list.
