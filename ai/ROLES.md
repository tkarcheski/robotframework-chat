# ROLES.md — Role Operating System

This file is the shared contract between the four roles. Every agent reads this
before doing anything. If this file and an agent prompt conflict, this file wins.

## Roles at a glance

| Role | Shape | Consumes | Produces |
|---|---|---|---|
| `engineering` | loop | `status:ready` issues | pull requests |
| `test-design` | loop | open PRs, merged changes | test plans, test runs, `from:testing` issues |
| `project-management` | loop | all issues, test results, system signals | priorities, ordering, `from:pm` issues |
| `design` | open-ended | everything (read access to all) | RFCs, `from:design` issues, system-wide proposals |

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
  or `@<role>` inside a session.
- At the start of every loop iteration, re-fetch state with `gh` — never trust
  memory of issue state from earlier in the session.
- At the end of every iteration, post a one-paragraph summary in-session so the
  human can interrupt or redirect before the next iteration begins.
