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

## Clarifying Questions (Default Behavior)

**Short or ambiguous prompts require clarification before acting.** When a user
prompt is brief, vague, or could be interpreted multiple ways, do NOT guess —
ask first. Review the codebase for current context, then ask targeted questions.

### When to ask

- The prompt is fewer than ~15 words and doesn't reference a specific file/function.
- The intent could mean multiple things (e.g. "fix the tests" — which tests? what's broken?).
- The request touches existing code but doesn't specify *how* to change it.
- The scope is unclear (one file vs. many, new feature vs. modification).

### What to ask

Always ground your questions in the current state of the codebase. Before asking,
scan relevant files so your questions are informed, not generic. Then ask questions
like:

1. **Intent** — Are you looking to simplify, refactor, extend an existing feature,
   or build something new?
2. **Scope** — Should this change be limited to a specific file/module, or is it
   cross-cutting?
3. **Existing patterns** — I see `<existing thing>` already does something similar.
   Should I build on that, replace it, or start fresh?
4. **Trade-offs** — There are a few ways to do this: `<option A>` vs `<option B>`.
   Which direction do you prefer?
5. **Priority** — Is this a quick fix, or should I invest in a robust solution?
6. **Testing** — What tier of testing should this have? (See `ai/CLAUDE.md` § Grading Tiers)
7. **Side effects** — This change would also affect `<X>`. Is that intended?

### How many questions

- Aim for 2–4 focused questions. Not a wall of text.
- If you can answer some questions yourself by reading the code, do that instead
  of asking.
- Group related questions together.

### When NOT to ask

- The prompt is specific and unambiguous (e.g. "rename `foo` to `bar` in `keywords.py`").
- The user has already provided detailed context or a multi-step plan.
- The user says "just do it" or explicitly asks you to skip questions.

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
- **Always include a version bump when submitting a PR.** Ask the user what the next version should be before bumping. Update the version in both `pyproject.toml` and `src/rfc/__init__.py`.

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
