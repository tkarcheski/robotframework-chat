# CLAUDE.md — Claude Code instructions

Read `ai/agents.md` for architecture, code style, and agent contract.
Read `ai/testing.md` for grading tiers and test rules.

---

## Quick reference

```bash
make install                  # Install all dependencies
pre-commit install            # Install git hooks (required before first commit)
uv run pytest                 # Run Python unit tests
pre-commit run --all-files    # Run all pre-commit checks
make code-quality-check       # Lint (ruff) + typecheck (mypy)
make robot-dryrun             # Validate Robot tests without execution
```

---

## Core workflow

1. **TDD is mandatory.** Every feature or fix must be paired with a pytest update.
   Write a failing test first, implement, then refactor.
2. **Resolve all errors.** Before committing, ensure zero failures from:
   - `uv run pytest`
   - `pre-commit run --all-files`
   - `make code-quality-check` (ruff + mypy)
3. **Atomic commits.** One idea per commit: `<type>: <summary>`.
   Types: `test:`, `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
4. **Never bundle unrelated changes** or mix formatting with logic.

---

## PR workflow

After a working solution is committed and all checks pass:

1. **Rebase onto `claude-code-staging`:**
   ```bash
   git fetch origin claude-code-staging
   git rebase origin/claude-code-staging
   ```
2. **Ask the user for the version bump** (`pyproject.toml` + `src/rfc/__init__.py`).
3. **Create the PR** using `gh pr create`.
4. **Monitor the PR for feedback.** Poll with:
   ```bash
   gh pr view <N> --comments
   gh api repos/tkarcheski/robotframework-chat/pulls/<N>/reviews
   ```
5. **Address all review comments** in new commits (don't amend until approved).
6. **Re-push and re-check** until the PR is approved.

---

## Rules

- `src/rfc/` is the single source of truth for all Python code.
- `robot/` is the single home for all Robot Framework tests.
- Type hints required on all new Python code. mypy must pass.
- Never use `Optional` for database dataclass fields — use concrete defaults.
- Use `RETURN` (not `[Return]`) in Robot Framework keywords.
- Every Robot test tagged with exactly one `tier:*` and one `verify:*` tag.
- New Robot test suites must be registered in `config/test_suites.yaml` and
  `config/local_models.yaml`.
- Always rebase onto `claude-code-staging`, not `main`.
- **Never commit `uv.lock`.** It is gitignored. Run `uv sync` to regenerate
  locally. `pyproject.toml` pins exact versions and is the source of truth.

---

## Clarifying questions

When a prompt is brief or ambiguous, ask 2–4 focused questions before acting.
When the prompt is specific and unambiguous, just do it.

---

## Environment

Copy `.env.example` to `.env` and edit before running integration tests.
Key variables: `OLLAMA_ENDPOINT`, `DEFAULT_MODEL`, `DATABASE_URL`.
See `ai/dev.md` § Environment Configuration for the full list.
