# CLAUDE.md — Claude Code persistent instructions

Read `@ai/CLAUDE.md` for grading tiers and test rules.

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
make code-quality-check               # Lint (ruff) + typecheck (mypy)
make robot-dryrun             # Validate Robot tests without execution

# Cross-platform alternative (works on Windows without make/bash):
uv run python tasks.py help           # List all available targets
uv run python tasks.py install        # Install dependencies
uv run python tasks.py check          # Lint + typecheck + coverage
uv run python tasks.py robot-dryrun   # Validate Robot tests
```

---

## Rules

- **Always read `ai/AGENTS.md` before starting any task.** This file contains critical agent architecture guidance and must be consulted first.
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
- **Every Robot test must be tagged** with exactly one `tier:*` (0–6) and one `verify:*` tag per `ai/CLAUDE.md` § Tagging Rules.
- **When adding a new Robot test suite**, register it in both `config/test_suites.yaml` (CI) and `config/local_models.yaml` (local cron). The hourly cron job (`scripts/cron_run_local_models.sh`) runs every suite listed in `local_models.yaml`.
- **Assume the user will make mistakes.** Validate requests against the codebase and confirmed decisions before executing. See `ai/AGENTS.md` § User Input Validation.
- **Always rebase onto `claude-code-staging`**, not `main`. This is the integration branch for all Claude Code work.

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
