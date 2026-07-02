# ROLES.md — Role Operating System

This file is the shared contract between the four roles. Every agent reads this
before doing anything. If this file and an agent prompt conflict, this file wins.

## Roles at a glance

| Role | Shape | Consumes | Produces | Git footprint |
|---|---|---|---|---|
| `engineering` | loop | `status:ready` issues | pull requests | creates issue-branch worktrees |
| `test-design` | loop | open PRs, merged changes | test plans, test runs, `from:testing` issues | joins PR-branch worktrees; owns `results` |
| `project-management` | loop | all issues, test results, system signals | priorities, ordering, `from:pm` issues | none (read + `gh` only); owns `monitoring/logs` |
| `design` | open-ended | everything (read access to all) | RFCs, `from:design` issues, system-wide proposals | own worktree for RFCs/prompt diffs; owns `elons-algorithm` |

## Label taxonomy (GitHub Issues)

**Status (exactly one per issue):**
- `status:triage` — newly filed, not yet vetted. Default for all new issues.
- `status:ready` — vetted, scoped, prioritized. The ONLY status engineering may pick up.
- `status:in-progress` — engineering has claimed it (assign yourself + comment the branch name).
- `status:blocked` — cannot proceed; comment must state the blocker.

**Priority (set only by project-management):**
- `P0` (drop everything) · `P1` (this loop) · `P2` (soon) · `P3` (backlog)

**Source (who filed it):**
- `from:testing` · `from:pm` · `from:design` · (none = human-filed)

**Type:**
- `type:bug` · `type:feature` · `type:quality` · `type:monitoring` · `type:design-debt`

## Hard rules

1. **Only project-management moves `status:triage` → `status:ready`** and assigns priority.
2. **Engineering only pulls `status:ready`**, highest priority first, oldest first within a priority.
3. **No role merges its own PR.** Engineering opens PRs; merging requires a passing
   test-design review (PR comment `TEST-PLAN: PASS`) or explicit human approval.
4. **One issue per branch, one branch per PR.** Branch naming: `<type>/<issue-number>-<slug>`.
5. **Every agent-filed issue** must include: repro/evidence, expected vs actual,
   affected area, and a `from:*` label. No vague issues.
6. **Test plans live in the repo** at `ai/test-plans/PR-<number>.md` and are committed
   on a `test/pr-<number>` branch or attached as a PR comment — pick one and stay consistent.
   New *tests* (as opposed to plans) must reach the reviewed PR: commit them to the PR
   branch, or open a PR from `test/pr-<number>` targeting that branch and link it in the
   verdict. `TEST-PLAN: PASS` is invalid while a new test is stranded on a side branch.
7. **Loops end cleanly.** When a loop's queue is empty, the agent posts a summary and
   stops — it does not invent work. Inventing work is design's job.
8. **Humans interrupt anything.** A human instruction in-session overrides loop order.
9. **Every role works in a worktree with its role identity set** (`ai/GIT.md`),
   never in the human's main checkout. Project-management, which writes no files,
   works read-only plus `gh`.
10. **Submodule pointer bumps only by the owning role** per the `ai/GIT.md`
    ownership table; CI rejects non-owner agent bumps. Merging always requires
    a human for now.
11. **Feedback before new work.** Every loop iteration FIRST services feedback
    on artifacts the role already owns — engineering: unresolved reviews,
    failing checks, and verdicts on its open PRs; test-design: stale verdicts
    and replies on its verdict threads; project-management: aging feedback
    nobody answered. Only when nothing you own is waiting on you may you pull
    new work. A PR stalled on unanswered feedback is the pipeline's definition
    of stuck.

## Automation north star

The steady state this system drives toward: **the human's only action is
reviewing and approving PRs.** Everything else — triage, prioritization,
implementation, feedback response, testing, verdicts, re-verdicts, process
repair — is handled by the roles within one loop iteration of the signal
appearing. Any human action other than PR approval (nagging a role, re-running
a check, manually routing feedback) is a defect in this contract: design owns
finding and fixing it. Today the sessions are human-launched and supervised;
the monitoring layers (`triage-issues-prs` skill) are the path to event-driven
wake-up.

## Git topology & concurrency (summary — full contract in ai/GIT.md)

All four roles run **simultaneously**, each in its own Claude Code session.
Isolation comes from git worktrees at `../AI/rfc/worktree/<branch>` — one per
*branch*, shared between roles that have business on that branch (test-design
commits tests in the worktree where engineering built the PR). Each role
commits under its own identity (`rfc-<role>-agent <role>@agents.rfc`,
worktree-scoped config) so every action is attributable. Submodules are
initialized per-worktree and pointer bumps belong to owning roles. If this
summary and `ai/GIT.md` disagree, `ai/GIT.md` wins.

## Communication contract

Roles never talk to each other directly — **GitHub is the message bus**, and
the labels/comments above are the protocol. Two consequences:

1. **Emit deliberately.** State changes are how your peers find out anything.
   An unlabeled issue, an uncommented claim, or an unpublished test plan is a
   message you failed to send. Each role prompt lists the exact signals it
   emits and watches.
2. **Poll deliberately.** No role is woken by events; you discover peer
   activity only when you re-fetch. Therefore: re-fetch your queue at the top
   of **every** iteration, and re-fetch the specific object (issue, PR) right
   before you mutate it — a claim race lost gracefully beats a duplicate PR.
   Idle loops re-poll on their iteration cadence; they do not exit just
   because one poll came back empty if the human asked for continuous
   operation. (Push delivery exists outside the sessions: the monitoring
   layers in the `triage-issues-prs` skill can wake agents on GitHub events —
   that is the upgrade path, not a thing loop roles rely on today.)

## Handoff map

```
                    ┌─────────────────────────────┐
                    ▼                             │
  status:ready ► ENGINEERING ──► PR ──► TEST-DESIGN
                    ▲                    │      │
                    │              PASS/FAIL  issues (from:testing, status:triage)
                    │                            ▼
              PROJECT-MANAGEMENT ◄── reviews issues, tests, system health
                    ▲       │
                    │     issues (from:pm) + priorities + ready promotion
                    │
                 DESIGN ──► issues (from:design) / RFCs in ai/rfcs/
```

## Session conventions

- Run each role in its own interactive Claude Code session: `claude --agent <role>`
  or `@<role>` inside a session. All four sessions may run at the same time.
- Start every session with the git ritual in `ai/GIT.md` (fetch, worktree,
  submodules, worktree-scoped identity).
- At the start of every loop iteration, re-fetch state with `gh` — never trust
  memory of issue state from earlier in the session.
- At the end of every iteration, post a one-paragraph summary in-session so the
  human can interrupt or redirect before the next iteration begins.

## The cast (flavor)

Each role charter opens with a light persona — seasoning only, never overriding
the rules above: **design** is **Elon Tusk** (delete-and-simplify, Elon's
algorithm), **engineering** is **Scotty** (honest checks, padded estimates),
**test-design** is **Mr. Meeseeks** (one verdict, then done), and
**project-management** is **Henry Gantt** (sequence, dependencies, critical
path). If a persona ever seems to suggest otherwise, this file still wins.
