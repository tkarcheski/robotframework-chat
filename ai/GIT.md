# GIT.md — Git Operating System

How the four roles share one repository without colliding. Every role reads
this before its first git operation. `ai/ROLES.md` carries a summary; if the
two conflict, **this file wins** on git topology and `ROLES.md` wins on role
boundaries.

Design assumption: **agents don't reliably follow rules.** Every rule here is
therefore backed by something mechanical — git's own invariants, attributable
identities, or a CI check at the human-gated merge. Prompts request; checks
enforce.

## Worktree layout

- Worktrees live at `../AI/rfc/worktree/<branch>` relative to the repo root
  (e.g. `/home/tyler/AI/github/AI/rfc/worktree/feat/123-slug`). Setup is the
  `rfc-worktree` skill — use it, don't hand-roll.
- **One worktree per branch, never per role.** Git enforces that a branch is
  checked out in at most one worktree, so two agents can never silently
  diverge the same branch — the second `worktree add` simply fails.
- The human's main checkout (`/home/tyler/AI/github/rfc`) is **off limits** to
  every role: no checkouts, no commits, no config writes there. Read-only
  operations (`git -C <root> log`, `worktree list`) are fine.

## Sharing protocol (worktrees are shared, not owned)

A worktree belongs to a *branch*, and any role with business on that branch
may work in it — the canonical case is test-design committing tests in the
worktree where engineering built the PR. Rules when entering a worktree you
didn't create:

1. `git status` must be clean. If it isn't, someone is mid-edit: stop, report,
   do not stash or reset another agent's work in progress.
2. `git pull --ff-only` before acting; `git pull --ff-only` again before
   pushing. Fast-forward only — never rebase or force-push a shared branch.
3. Never `reset --hard`, `checkout -- .`, or `clean` in a worktree you didn't
   create.
4. The role that created a worktree removes it (`git worktree remove`, never
   `rm -rf`) after its branch merges or is abandoned.

## Session start ritual (every role, every session)

```bash
git fetch origin
# create or enter your worktree (rfc-worktree skill), then inside it:
git -C "$WT" submodule update --init        # worktrees do NOT inherit submodules
git -C "$WT" config extensions.worktreeConfig true
git -C "$WT" config --worktree user.name  "rfc-<role>-agent"
git -C "$WT" config --worktree user.email "<role>@agents.rfc"
```

**The `--worktree` flag is mandatory.** Linked worktrees share one
`.git/config`; a plain `git config user.name` re-identifies every agent and
the human at once. Worktree-scoped config requires `extensions.worktreeConfig`
to be enabled first (this one shared-scope write is allowed — it only enables
the mechanism).

## Per-role identity

| Role | user.name | user.email |
|---|---|---|
| engineering | `rfc-engineering-agent` | `engineering@agents.rfc` |
| test-design | `rfc-test-design-agent` | `test-design@agents.rfc` |
| project-management | `rfc-project-management-agent` | `project-management@agents.rfc` |
| design | `rfc-design-agent` | `design@agents.rfc` |

Every commit is attributable to the role that made it. Anything *not* ending
in `@agents.rfc` is a human, and humans outrank agents everywhere. (Future
hardening: separate GitHub accounts and tokens per role; identity-by-config is
v1.)

## Submodules

Three submodules exist (`.gitmodules`): `results` (LFS-backed test output —
see the `audit-robot-reports` skill for the robotmetrics/LFS quirks),
`monitoring/logs`, and `.claude/skills/elons-algorithm`.

**Ownership — only the owning role may commit a pointer bump:**

| Submodule | Owner |
|---|---|
| `results` | test-design |
| `monitoring/logs` | project-management |
| `.claude/skills/elons-algorithm` | design |

For everyone else a dirty submodule pointer is **noise**: never `git add` it
(beware `git add -A` / `git commit -a`, which swallow gitlinks silently). If
your work genuinely needs a bump, file an issue for the owning role.

**Enforcement:** CI runs `scripts/check_submodule_ownership.py` on every PR.
A pointer bump authored by a non-owner agent identity fails the build; bumps
authored by humans always pass. The script's table mirrors this file — update
both together. Until further notice **every merge also requires a human** —
agents never merge, regardless of verdicts.

## Hygiene

- `git worktree list` shows all active worktrees; a worktree whose branch has
  merged is stale — project-management flags these in its systems sweep, and
  the creating role removes them.
- `git worktree prune` cleans metadata for manually-deleted paths.
- Re-fetch before acting on any belief about remote state; worktrees make it
  easy to act on a stale picture of a shared branch.

## Out of scope (deliberately, for now)

- Shadow/variant agents running prompt variants on the same queue.
- Per-role GitHub accounts and tokens.
- Agent-initiated merges.
