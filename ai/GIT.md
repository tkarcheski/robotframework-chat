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

- Worktrees live at `/home/tyler/AI/rfc/worktree/<branch>`
  (e.g. `/home/tyler/AI/rfc/worktree/fix/426-continue-on-model-failure`).
  The `rfc-worktree` skill scaffolds setup (env copy, install, baseline
  checks); where this contract and the skill disagree — branch naming,
  identity, submodules — **this contract wins**. Role branches are named per
  `ai/ROLES.md` (`<type>/<issue-number>-<slug>`), never the skill's random
  `claude/<slug>-<rand5>` scheme, and never `worktree add -B` onto a branch
  that might already exist — plain `worktree add` fails loudly instead of
  resetting someone's work.
- **One worktree per branch, never per role.** Git enforces that a branch is
  checked out in at most one worktree, so two agents can never silently
  diverge the same branch — the second `worktree add` simply fails.
- The human's main checkout (`/home/tyler/AI/github/rfc`) is **off limits** to
  every role: no checkouts, no commits, no config writes there. Read-only
  operations (`git -C <root> log`, `worktree list`) are fine.

## Sharing protocol (worktrees are shared, not owned)

A worktree belongs to a *branch*, and any role with business on that branch
may work in it — the canonical case is test-design committing tests in the
worktree where engineering built the PR. Sharing is **sequential, never
concurrent**: one role mutates a worktree at a time — two processes editing
the same working tree contend on the index and overwrite each other no matter
what branch rules say. The lease makes that mechanical. Rules when entering a
worktree you didn't create:

1. **Take the lease first:** `git worktree lock --reason "<role>: <task>" <path>`
   before your first mutation; `git worktree unlock <path>` when done. Already
   locked means in use — wait or coordinate via PR comment; never work through
   someone else's lease. Creating roles lock at creation and unlock when they
   hand the branch off (e.g. when the PR opens).
2. `git status` must be clean. If it isn't, someone is mid-edit: stop, report,
   do not stash or reset another agent's work in progress.
3. `git pull --ff-only` before acting; `git pull --ff-only` again before
   pushing. Fast-forward only — never rebase or force-push a shared branch.
4. Never `reset --hard`, `checkout -- .`, or `clean` in a worktree you didn't
   create — and never touch its `--worktree` config: that identity belongs to
   the creating role (see Per-role identity).
5. The role that created a worktree removes it (`git worktree remove`, never
   `rm -rf`) after its branch merges or is abandoned.

## Session start ritual (every role, every session)

```bash
git fetch origin
# create or enter your worktree (rfc-worktree skill), then inside it:
git -C "$WT" submodule update --init        # worktrees do NOT inherit submodules
# ONLY if you created this worktree — set its default identity:
git -C "$WT" config extensions.worktreeConfig true
git -C "$WT" config --worktree user.name  "rfc-<role>-agent"
git -C "$WT" config --worktree user.email "<role>@agents.rfc"
```

**The `--worktree` flag is mandatory** when setting a default identity.
Linked worktrees share one `.git/config`; a plain `git config user.name`
re-identifies every agent and the human at once. Worktree-scoped config
requires `extensions.worktreeConfig` enabled first (this one shared-scope
write is allowed — it only enables the mechanism).

## Per-role identity & sign-offs

| Role | user.name | user.email |
|---|---|---|
| engineering | `rfc-engineering-agent` | `engineering@agents.rfc` |
| test-design | `rfc-test-design-agent` | `test-design@agents.rfc` |
| project-management | `rfc-project-management-agent` | `project-management@agents.rfc` |
| design | `rfc-design-agent` | `design@agents.rfc` |

**Worktree config is the creating role's default identity only.** Config is
per-worktree, not per-process: if a sharing role rewrote it, the creator's
next commit would be mis-attributed (and a mis-attributed commit is exactly
what the ownership guard trusts). So:

- **Creating role:** set the `--worktree` config once at creation; commit
  normally with `-s`.
- **Any other role committing in a shared worktree:** never edit the config;
  carry your identity on the command itself:

  ```bash
  git -C "$WT" -c user.name="rfc-<role>-agent" -c user.email="<role>@agents.rfc" \
      commit -s -m "..."
  ```

**Every agent commit is signed off and names its model.** Two trailers are
mandatory on agent-authored commits:

```bash
git -C "$WT" commit -s --trailer "Model:<model-id>" -m "..."
# produces:  Signed-off-by: rfc-design-agent <design@agents.rfc>
#            Model: claude-opus-4-8
```

`commit -s` derives `Signed-off-by:` from the identity in effect, so the
trailer names the role that actually committed even in shared worktrees; the
`Model:` trailer records which model was driving the role (the same role may
be run by different models — track who *and* what said what).
`git log --format='%h %ae %(trailers:key=Signed-off-by,valueonly) %(trailers:key=Model,valueonly)'`
shows full attribution at a glance. **Enforced by CI:**
`scripts/check_agent_signoffs.py` fails any PR containing an agent-authored
commit missing either trailer. Author/sign-off mismatches are flagged by
project-management's sweep rather than auto-failed (they can be legitimate
after a history rewrite). GitHub comments carry the same attribution: every
agent-posted issue/PR comment ends with a `— <role> role` signature line.

Anything *not* ending in `@agents.rfc` is a human, and humans outrank agents
everywhere. (Future hardening: separate GitHub accounts and tokens per role;
identity-by-config is v1.)

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
| `vendor/skill-packs/*` (all external skill packs, see #447) | design |
| `knowledge` (the tiered brain, see #454) | design |

External resources follow the **fork-first policy**: never submodule an
upstream you don't control — fork it under `tkarcheski/*` and submodule the
fork, so upstream changes only land via a deliberate, reviewable pointer bump.

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
