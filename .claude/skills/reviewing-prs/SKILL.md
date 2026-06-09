---
name: reviewing-prs
description: >-
  How to review a pull request in robotframework-chat: picking the right scope
  (whole-branch vs remote-only vs uncommitted), gh tooling caveats, verifying
  claims against the actual files before recommending changes, and the exact
  report structure (quality, suggestions, risks, coverage, security, verdict).
when_to_use: >-
  Trigger when the user invokes /review, asks you to review a PR or branch, or
  asks for feedback on a diff in this repo. These are the lessons from real
  review sessions, not the slash-command body itself.
---

# Reviewing a pull request

These rules aren't in the `/review` slash-command body — they're the lessons
from real review sessions on this repo.

## Pick the right scope

- **No PR number provided + active branch with unpushed commits:** review the
  whole branch as it would land, not just the remote diff. Combine three views:
  1. `git log --oneline origin/<base>..HEAD` — commits on the branch
  2. `git diff origin/<base>...HEAD` — what reviewers will see after push
  3. `git diff` / `git status --short` — uncommitted working-tree changes
- **Remote-only review (PR already pushed and matches HEAD):** `gh pr diff <N>`
  is authoritative. Call out remote vs local divergence so the user knows what
  reviewers see *today* vs what will land after the next push.
- **Stale PR body:** if the remote PR description doesn't match the current
  commit set, flag it explicitly — the body will need a force-push update too.

## Tooling caveats

- `gh pr diff <N> -- <file>` is **not supported** ("accepts at most 1 arg(s)").
  Save the full diff once: `gh pr diff <N> > /tmp/pr-diff.txt`. Then use `grep
  -nE "^diff --git"` to locate file boundaries and `Read` with `offset`/`limit`
  to inspect specific files. Don't try to filter via `gh` flags.
- For large PRs, prefer `--stat` first (`git diff origin/<base>...HEAD --stat`)
  to triage which files are mechanical vs. substantive before reading line diffs.

## Verify before recommending

- Never recommend a code change based on memory of the codebase. Open the file
  (or the diff) and confirm the line still says what you think before proposing
  an edit. Memory rots faster than the code.
- If the diff suggests a function exists, `grep -n "def <name>"` the file (or the
  diff) before referencing it. Phantom function references are a common
  review-time bug.

## What to actually report

Lead with the *overview* in 1-3 sentences: what the PR does and the rough shape
(commits, files, additions/deletions). Then sections in this order:

1. **Code quality and style** — what's good, then small nits.
2. **Specific suggestions for improvements** — numbered, each with file/line.
3. **Potential issues / risks** — a short severity-tagged table works well when
   there are 3+ items.
4. **Test coverage** — concrete numbers (e.g., "2767 passed, 4 new tests"), not
   vague claims.
5. **Security considerations** — name the threat model (path traversal, shell
   injection, SQL injection, secrets leakage) and say *why* this PR is safe from
   each, not just "no concerns."
6. **Verdict** — one sentence: ready to push, needs follow-ups (list them), or
   blocked.

Keep it concise. A review the user can read in under a minute and act on beats a
thorough one that gets skimmed.
