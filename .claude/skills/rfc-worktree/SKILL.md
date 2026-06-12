---
name: rfc-worktree
description: >-
  Sets up new rfc (robotframework-chat) work on its own branch in an isolated
  git worktree at ../AI/rfc/worktree/<branch>. Branches from a base of the
  user's choice (defaults to origin/claude-code-staging), copies .env, runs
  `uv sync`, and runs the CLAUDE.md baseline checks so you land on a green,
  isolated checkout. Prefer this over the generic using-git-worktrees skill when
  the working directory is rfc.
when_to_use: >-
  Trigger when the user says "set up a worktree", "make a worktree", "start a
  new feature/branch in rfc", "give me a fresh rfc branch", or similar —
  including when they don't say the word "worktree" but are clearly opening a
  new rfc session that should not pollute the current checkout.
disable-model-invocation: true
---

# rfc-worktree

## What this is

A one-shot setup for a fresh, isolated rfc branch. After this skill runs you'll
have a new worktree at `../AI/rfc/worktree/<branch>`, a clean Python env, a
working `.env`, and a green baseline — i.e. you can start writing code without
any further yak-shaving.

The repo's normal session-startup ritual (see `CLAUDE.md` § Session startup)
creates a branch in place. This skill is for the cases where you want the
branch *and* an isolated checkout — for example, working on multiple features
at once, or keeping a long-running experiment off your main checkout.

If you're already inside a linked worktree (`git rev-parse --git-dir` differs
from `git rev-parse --git-common-dir`), stop and tell the user. Don't create a
nested worktree.

## Step 1 — Confirm you're in the rfc repo

```bash
git -C "$PWD" rev-parse --show-toplevel
```

The top-level should end in `/rfc` (the user keeps it at
`/home/tyler/AI/github/rfc`). If it doesn't, ask the user where they want the
worktree rooted before continuing — this skill's path defaults assume the rfc
layout and will produce confusing paths elsewhere.

## Step 2 — Gather inputs

**Role sessions skip the question.** If you are a role agent (engineering,
test-design, project-management, design), `ai/GIT.md` already dictates both
inputs: `BRANCH="<type>/<issue-number>-<slug>"` (no random suffix) and
`BASE="origin/claude-code-staging"`. Use them and go straight to Step 3 with
plain `git worktree add` (no `-B` — see below).

Otherwise, ask **one** multiple-choice question that bundles both inputs. Use
the format the user prefers (see `CLAUDE.md` § Questions):

> Two quick inputs before I create the worktree:
>
> **Short slug for the branch** (will become `claude/<slug>-<rand5>`):
> a) <propose something based on recent conversation, e.g. "ast-foundation">
> b) <one alternative if obvious>
> c) Let me type it
>
> **Base branch** to branch from:
> a) `origin/claude-code-staging` (matches CLAUDE.md default)
> b) Current HEAD
> c) Let me type a ref

Then assemble:

```bash
SLUG="<user's chosen slug>"                          # kebab-case, no spaces
RAND5=$(openssl rand -hex 3 | cut -c1-5)             # 5 hex chars
BRANCH="claude/${SLUG}-${RAND5}"
BASE="<user's chosen base ref>"                      # e.g. origin/claude-code-staging
```

If the user picks `origin/claude-code-staging`, run `git fetch origin
claude-code-staging` first so the ref is up to date.

## Step 3 — Create the worktree

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
WORKTREE_PATH="${REPO_ROOT}/../AI/rfc/worktree/${BRANCH}"

git worktree add -B "$BRANCH" "$WORKTREE_PATH" "$BASE"
cd "$WORKTREE_PATH"
```

Why `-B` (capital): create-or-reset. If a stale branch with the same name
exists from a previous abandoned session, `-B` resets it to `$BASE` instead of
erroring out. That's the user's reference command and matches how they like to
work — collisions on `claude/<slug>-<rand5>` are vanishingly unlikely thanks
to the random suffix, but `-B` keeps the skill idempotent.

**Exception — role-contract branches (`<type>/<n>-<slug>`, per `ai/GIT.md`):
use plain `git worktree add`, never `-B`.** These names are deterministic, so
a collision means the branch genuinely exists (another session's work);
`-B` would silently reset it. Let the command fail loudly and investigate.

If `git worktree add` fails because the path already exists as a worktree, run
`git worktree list` and ask the user whether to reuse it, remove it
(`git worktree remove`), or pick a new slug. Never delete someone else's
in-progress work without confirmation.

The path `../AI/rfc/worktree/<branch>` resolves relative to the rfc repo root,
so from `/home/tyler/AI/github/rfc` it lands at
`/home/tyler/AI/github/AI/rfc/worktree/<branch>`. That's the layout the user
has chosen; don't second-guess it.

## Step 4 — Wire up the new checkout

Run these in order; stop and surface any failure to the user before
continuing.

```bash
# 4a. Copy .env from the source repo so DEFAULT_MODEL / OLLAMA_ENDPOINT /
#     DATABASE_URL etc. all work in the new checkout. .env is gitignored,
#     so worktrees don't get it automatically.
if [ -f "${REPO_ROOT}/.env" ]; then
  cp "${REPO_ROOT}/.env" .env
else
  echo "warning: no .env in source repo; copy .env.example and edit before running integration tests"
  cp .env.example .env  # best-effort
fi

# 4b. Install Python dependencies. uv.lock is gitignored on purpose;
#     pyproject.toml pins versions, so uv sync gives a clean install.
uv sync

# 4c. Initialize submodules — worktrees do NOT inherit them, and several
#     targets (robot runs, results archiving) assume they exist.
git submodule update --init

# 4d. Role sessions only: set the worktree-scoped role identity per ai/GIT.md
#     (plain `git config` here would rewrite the SHARED .git/config and
#     re-identify every other session — the --worktree flag is mandatory).
git config extensions.worktreeConfig true
git config --worktree user.name  "rfc-<role>-agent"
git config --worktree user.email "<role>@agents.rfc"
```

If `uv sync` fails, fix it before going further — a broken env will cascade
into every check that follows.

## Step 5 — Run the baseline checks

These match the pre-commit verification suite in `CLAUDE.md`. The point isn't
to pass them as a gate for *your* work — it's to confirm the worktree starts
on a green baseline, so any failure you see later is attributable to your
changes and not pre-existing rot on `claude-code-staging`.

```bash
uv run pytest                  # unit tests
pre-commit run --all-files     # yaml/json/whitespace/ruff/mypy hooks
make code-quality-check        # ruff + mypy
make robot-dryrun              # Robot tests parse correctly
```

Capture pass/fail for each. If any of them fails, **do not** try to fix it
silently. Report the failure to the user with the relevant output and ask
how to proceed:

> Baseline check `<name>` failed on a fresh worktree off `<base>`. Options:
> a) Investigate now — likely a regression on `<base>` itself
> b) Proceed anyway — I'll flag this failure in my session notes
> c) Abort and tear down the worktree

## Step 6 — Report

```
Worktree ready
  path:    <full path>
  branch:  <branch name>
  base:    <base ref>  (sha <short-sha>)
  env:     .env copied from source repo / created from .env.example
  uv sync: ok
  pytest:           <pass N / fail M>
  pre-commit:       <ok / failed>
  code-quality:     <ok / failed>
  robot-dryrun:     <ok / failed>

Next: cd <full path> and start working.
```

If you stayed in the worktree across step boundaries, also remind the user
that your shell's `cd` doesn't persist back to their terminal — they may need
to `cd` there themselves in another window.

## Common pitfalls

- **Don't create a worktree inside another worktree.** Run the `--git-dir`
  vs `--git-common-dir` check from Step 1 first.
- **Don't skip `.env` propagation.** Integration tests silently degrade
  without it (DEFAULT_MODEL falls back, DATABASE_URL is missing). The user
  finds out 10 minutes later when nothing works.
- **Don't run `git worktree add` from a sub-directory** without resolving the
  relative path. The skill above uses `$REPO_ROOT/..` so the worktree lands
  in the same place no matter where the shell happens to be.
- **Don't `rm -rf` an existing worktree path.** If `git worktree add` errors
  on path collision, use `git worktree remove` (which detaches it from git's
  metadata correctly) and only after the user agrees.
- **Don't bundle this with `--no-verify` commits or any other shortcut to make
  failing checks go away.** The whole point of the baseline run is to catch
  rot early; suppressing it defeats the skill.
