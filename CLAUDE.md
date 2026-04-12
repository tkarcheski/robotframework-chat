# CLAUDE.md — Claude Code instructions

Read `ai/agents.md` for architecture, code style, and agent contract.
Read `ai/testing.md` for grading tiers and test rules.

---

## Session startup

Every new session begins with a repo health check. Do this before writing any
code:

1. **Create a feature branch** from `claude-code-staging`:
   ```bash
   git fetch origin claude-code-staging
   git checkout -b claude/<short-description>-<random5> origin/claude-code-staging
   ```
   One branch per session. One session per feature.

2. **Pre-check the repo:**
   ```bash
   uv run pytest
   pre-commit run --all-files
   make code-quality-check
   make robot-dryrun
   ```
   If anything fails, fix it or ask the user before proceeding. Do not add new
   work on top of a broken baseline.

3. **Scan for staleness:**
   - Check `humans/TODO.md` for relevant context.
   - Look for `TODO`, `FIXME`, or dead code in files you'll touch.
   - Flag findings to the user with a multiple-choice question:
     a) Fix now as a separate commit
     b) Defer to a follow-up task
     c) Ignore — it's intentional

4. **Ask clarifying questions.** See § Questions below.

---

## Questions

**Default behavior:** Ask 2–4 multiple-choice questions before acting on any
ambiguous or multi-step task. Present concrete options, not open-ended prompts.

**When to ask:**
- The task touches > 3 files or crosses module boundaries.
- The task could be interpreted multiple ways.
- Scope is growing beyond the original request.
- A check fails and the fix isn't obvious.
- You're about to make a directional decision (API design, naming, architecture).
- Something in the repo contradicts the request.

**When not to ask:** The prompt is specific, unambiguous, and scoped to a single
file or function. Just do it.

**Format:** Always prefer multiple-choice:
```
Before I start, a few questions:

1. The grader module has two unused helper functions. Should I:
   a) Remove them in a separate cleanup commit
   b) Leave them — they're planned for future use
   c) Flag them in humans/TODO.md

2. This change could go in keywords.py or a new file. Preference:
   a) Add to keywords.py (keeps it centralized)
   b) New file safety_keywords.py (separates concerns)
```

**If a process isn't clear:** Ask. If CLAUDE.md, `ai/agents.md`, or
`ai/testing.md` could be improved, say so and propose a change.

---

## Core workflow

1. **TDD is mandatory.** Every feature or fix must be paired with a pytest
   update. Write a failing test first, implement, then refactor.
2. **Resolve all errors.** Before committing, ensure zero failures from the
   full verification suite (see § Pre-commit verification).
3. **Atomic commits.** One idea per commit: `<type>: <summary>`.
   Types: `test:`, `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
4. **Never bundle unrelated changes** or mix formatting with logic.
5. **Follow external checklists when provided.** If the user points to a
   specific checklist (e.g., a Rufus plan, a TODO list), follow that instead
   of the default workflow. The checklist takes precedence.

---

## Pre-commit verification

Run **all** of the following before every commit. No exceptions unless the user
explicitly says to skip a step.

```bash
uv run pytest                     # Python unit tests — must pass
pre-commit run --all-files        # Hooks: yaml, json, whitespace, ruff, mypy
make code-quality-check           # Lint (ruff) + typecheck (mypy)
make robot-dryrun                 # Validate Robot tests parse correctly
```

After checks pass, **self-review the diff:**

```bash
git diff --staged
```

Check for:
- Accidental changes outside the intended scope.
- Debug prints, commented-out code, or leftover `print()` statements.
- Unresolved `TODO` or `FIXME` markers (resolve or ask the user).
- New files outside `src/rfc/` (Python) or `robot/` (Robot tests).
- Missing type hints on new Python code.
- Robot tests missing `tier:*` or `verify:*` tags.
- Violations of rules in `ai/agents.md` or `ai/testing.md`.

If anything looks wrong, fix it before committing. If unsure, ask:
```
I noticed X in my staged changes. Should I:
a) Fix it now
b) Leave it — it's intentional
c) Split it into a separate commit
```

---

## Branching and commits

**Multiple agents may work on this repo simultaneously.** Follow these rules
to avoid conflicts:

- **One branch per session.** Create `claude/<description>-<random5>` at
  session start. All work for this session goes on this branch.
- **Rebase before pushing:**
  ```bash
  git fetch origin claude-code-staging
  git rebase origin/claude-code-staging
  ```
- **Small, atomic commits.** Each commit should be:
  - Independently reviewable (a reviewer can understand it without context).
  - Bisectable (if it introduced a bug, `git bisect` would find it).
  - Testable (checks pass at every commit, not just the final one).
- **Never commit `uv.lock`.** It is gitignored. `pyproject.toml` pins versions.

---

## PR workflow

The PR template lives at `.github/PULL_REQUEST_TEMPLATE.md`. Claude must
follow it and fill in every section — no placeholders, no "see above."

### Before creating the PR

1. **Rebase onto `claude-code-staging`:**
   ```bash
   git fetch origin claude-code-staging
   git rebase origin/claude-code-staging
   ```
2. **Self-review the full PR diff:**
   ```bash
   git diff origin/claude-code-staging...HEAD
   ```
   Verify the diff matches the intended scope. No stray changes.

3. **Run the full verification suite** and capture output:
   ```bash
   uv run pytest 2>&1 | tee /tmp/pr-pytest.txt
   pre-commit run --all-files 2>&1 | tee /tmp/pr-precommit.txt
   make code-quality-check 2>&1 | tee /tmp/pr-quality.txt
   make robot-dryrun 2>&1 | tee /tmp/pr-dryrun.txt
   ```

4. **Ask the user for the version bump** (`pyproject.toml` + `src/rfc/__init__.py`).

### Writing the PR description

Fill in the template completely:

- **Summary:** What changed and why, in 1–3 sentences. Link the issue.
- **How to review:** Guide the reviewer through the changes:
  - Name the file and function to start with.
  - List key changes in the order they should be reviewed.
  - Call out what's mechanical/ignorable vs. what needs careful thought.
- **Evidence of testing:** Paste actual command output from the verification
  suite into the collapsible sections. The reviewer should see proof, not
  promises. Include:
  - `uv run pytest` output
  - `pre-commit run --all-files` output
  - `make code-quality-check` output
  - `make robot-dryrun` output
- **Critical changes:** If the PR touches public APIs, database schema, config
  formats, CI behavior, or listener contracts — explain the impact and
  migration path. If nothing critical, write "None."
- **Checklist:** Complete every item before submitting. Check them off in the
  PR body.

### Example "How to review" section

```markdown
## How to review

**Start here:** Read `src/rfc/safety_grader.py` — the regex patterns in
`grade_safety()` are the core change.

**Key changes:**
1. `src/rfc/safety_grader.py` — new refusal-detection patterns (critical)
2. `tests/test_safety_grader.py` — test cases covering each new pattern
3. `robot/safety/tests/refusal.robot` — Robot integration test (mechanical)

**What to ignore:** The Robot test is a straightforward keyword call using
the same pattern as existing safety tests. Focus review time on the regex
patterns in step 1.
```

### After creating the PR

5. **Create the PR** using `gh pr create`. The template auto-populates.

6. **Monitor the PR for feedback.** Always poll for reviews:
   ```bash
   gh pr view <N> --comments
   gh api repos/tkarcheski/robotframework-chat/pulls/<N>/reviews
   ```
   Address all feedback like a senior developer:
   - Acknowledge the comment.
   - Implement the fix in a new commit (don't amend until approved).
   - Re-run the full verification suite.
   - Reply to the comment explaining what changed and paste updated test output
     if the fix affected behavior.

7. **Re-push and re-check** until the PR is approved.

---

## Refactoring

Refactoring is part of the workflow, not a separate activity. Apply it at
these trigger points:

| Trigger | Scope |
|---------|-------|
| **After completing a feature** | Refactor only the code you touched. |
| **After a version bump** | Broader cleanup — dead code, naming, structure. |
| **Session startup scan** | Flag dead code and staleness to the user (see § Session startup). |
| **Spotted during work** | Ask before fixing. Don't silently clean up nearby code. |

For dead code removal, always ask first:
```
I found unused function `_old_helper()` in grader.py:142. Should I:
a) Remove it in a cleanup commit
b) Leave it — it's used elsewhere or planned
c) Add a TODO to revisit later
```

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

## Error recovery

When a check fails:

1. **Read the error.** Understand the root cause before attempting a fix.
2. **Fix if obvious.** Lint errors, missing type hints, trivial test failures —
   fix and re-run.
3. **Ask if not obvious.** If the fix isn't clear after one attempt, ask:
   ```
   `make code-quality-check` failed with: <error>
   I tried: <what you did>
   It didn't work because: <why>

   Options:
   a) Try <alternative approach>
   b) Skip this check for now and revisit
   c) I need more context — can you explain <specific thing>?
   ```
4. **Never loop silently.** If you've tried twice and it's still failing,
   escalate to the user. Don't retry the same fix.

---

## Environment

Copy `.env.example` to `.env` and edit before running integration tests.
Key variables: `OLLAMA_ENDPOINT`, `DEFAULT_MODEL`, `DATABASE_URL`.
See `ai/dev.md` § Environment Configuration for the full list.
