---
name: creating-prs
description: >-
  The robotframework-chat pull-request workflow: rebase onto claude-code-staging,
  self-review the full diff, run the verification suite and capture output, bump
  the version, fill in every section of the PR template (summary, how-to-review,
  evidence of testing, critical changes, checklist), create the PR, and monitor
  it for feedback.
when_to_use: >-
  Trigger when the user asks to open, create, or submit a pull request, to
  prepare a branch for a PR, or when wrapping up a feature where a PR is the next
  step.
---

# Creating a pull request

The PR template lives at `.github/PULL_REQUEST_TEMPLATE.md`. Follow it and fill
in every section — no placeholders, no "see above."

## Before creating the PR

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

4. **Bump the version** (`pyproject.toml` + `src/rfc/__init__.py`).
   Default to **patch** (`x.y.Z`) — that fits almost every PR (bug fixes,
   internal refactors, audit-driven hardening, doc tweaks). Bump and commit as a
   separate `chore: bump version to X.Y.Z` commit without asking. Only stop and
   ask the user when the change genuinely doesn't fit a patch:

   - Minor (`x.Y.0`) — a new public keyword, a new public API on an existing
     class, a new test suite or grader, or behaviour that materially changes how
     downstream consumers grade tests.
   - Major (`X.0.0`) — a removed/renamed public keyword, a changed keyword
     signature, a database schema change without a migration, or any change that
     requires downstream code edits.
   - Skip — pure-docs PRs, CI-only changes, or work that doesn't touch
     installable code.

   When unsure, ask:
   ```
   Version bump for this PR — defaulting to patch (x.y.Z). Override?
   a) Patch (recommended)
   b) Minor — <one-line reason this isn't a patch>
   c) Major — <one-line reason this is breaking>
   d) Skip
   ```

## Writing the PR description

Fill in the template completely:

- **Summary:** What changed and why, in 1–3 sentences. Link the issue.
- **How to review:** Guide the reviewer through the changes:
  - Name the file and function to start with.
  - List key changes in the order they should be reviewed.
  - Call out what's mechanical/ignorable vs. what needs careful thought.
- **Evidence of testing:** Paste actual command output from the verification
  suite into the collapsible sections. The reviewer should see proof, not
  promises. Include `uv run pytest`, `pre-commit run --all-files`,
  `make code-quality-check`, and `make robot-dryrun` output.
- **Critical changes:** If the PR touches public APIs, database schema, config
  formats, CI behavior, or listener contracts — explain the impact and migration
  path. If nothing critical, write "None."
- **Checklist:** Complete every item before submitting. Check them off in the PR
  body.

### Example "How to review" section

```markdown
## How to review

**Start here:** Read `src/rfc/safety_grader.py` — the regex patterns in
`grade_safety()` are the core change.

**Key changes:**
1. `src/rfc/safety_grader.py` — new refusal-detection patterns (critical)
2. `tests/test_safety_grader.py` — test cases covering each new pattern
3. `robot/safety/tests/refusal.robot` — Robot integration test (mechanical)

**What to ignore:** The Robot test is a straightforward keyword call using the
same pattern as existing safety tests. Focus review time on the regex patterns
in step 1.
```

## After creating the PR

5. **Create the PR** using `gh pr create`. The template auto-populates. (In a
   remote/web session without `gh`, use the GitHub MCP tools instead.)

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
