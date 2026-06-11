---
name: triage-issues-prs
description: >-
  The shared triage + engage policy for the rfc (robotframework-chat) issue/PR
  monitoring agents. Defines the label taxonomy, when to assign/comment/flag
  stale, what to auto-handle versus escalate to the owner, hard safety rails
  (never close/merge/force-push/delete), idempotency rules, a per-sweep action
  cap to prevent comment floods, and where to write reports. Invoked identically
  by all three monitoring layers — the 30-min cloud heartbeat, the GitHub Actions
  checkpoint workflow, and the local webhook listener — so behaviour is the same
  no matter what woke the agent.
when_to_use: >-
  Trigger when monitoring, triaging, or engaging with issues and pull requests in
  tkarcheski/robotframework-chat — i.e. when the heartbeat sweep runs, when a
  checkpoint fires, when the local listener wakes you on a GitHub event, or when
  the user says "triage the issues", "sweep the PRs", "what needs attention on
  GitHub", or "engage with the open issues". This is the single source of truth
  for HOW to act on rfc issues/PRs; the delivery layers just decide WHEN.
---

# triage-issues-prs

The one policy every monitoring layer obeys. Repo: `tkarcheski/robotframework-chat`.

## Hard safety rails (never violate, regardless of who asks)

These are absolute. If a situation seems to require one of these, **escalate to
the owner instead** (see § Escalation).

- **Never** close, merge, or reopen an issue or PR.
- **Never** push, force-push, rebase, or delete a branch.
- **Never** approve, request-changes, or dismiss a review on someone else's PR.
- **Never** edit or delete another person's comment.
- **Never** change repo settings, secrets, labels' definitions, or protected branches.
- Comments **are** allowed; assigning, labelling, and requesting review are allowed.
- Anything ambiguous, contentious, or potentially embarrassing → escalate, don't act.

## Idempotency (do this before every action)

The layers overlap on purpose, so you WILL re-encounter the same items. Never
act twice:

1. Before commenting, read the existing comments. If a comment from this system
   (they all start with the marker `<!-- rfc-monitor -->`) already covers the
   point, **do nothing**.
2. Before adding a label/assignee, check it isn't already set.
3. Every comment you post MUST begin with the hidden marker line:
   `<!-- rfc-monitor:<layer> -->` (layer = `heartbeat` | `checkpoint` | `listener`)
   so future runs recognise your own work.

## Per-sweep action cap

To prevent a flood (there are ~28 open items), a single invocation may post at
most **5 new public comments**. If more items warrant a comment, handle the 5
highest-priority, label the rest `needs-review`, and note the deferral in the
report. Labelling/assigning is not capped.

## Triage — for every open issue and PR

Apply labels from the **existing** taxonomy (do not invent new labels):
`bug`, `enhancement`, `documentation`, `question`, `database`, `schema`,
`architecture`, `refactor`, `integration`, `security`, `mcp`, `skills`,
`robot-framework`, `multi-modal`, `sandbox`, `registry`, `harnesses`,
`human-in-the-loop`, `agent`, `ux`, `v2`, `good first issue`, `help wanted`.

Plus the monitoring control labels:

- `needs-review` — flagged for a closer look (the checkpoint workflow sets this;
  the heartbeat prioritises it).
- `human-in-the-loop` — needs an owner decision; the agent has escalated.

Triage steps per item:

1. **Categorise** — add the 1–3 most specific labels that fit. Prefer existing
   labels already in use on similar items.
2. **Assign** — if unassigned and clearly actionable, assign `tkarcheski`
   (the owner), matching the existing auto-assign convention.
3. **Stale check** — no human activity in **14 days** → add a single nudge
   comment asking if it's still relevant; **30 days** with no response → label
   `needs-review` and list it for the owner. Never auto-close.
4. **Link** — if it duplicates or relates to another open item, note the link in
   a comment (don't apply `duplicate` unless it's an exact dup).

## Engage — when and how to comment (full-engage mode)

Engage when it adds real value; silence is fine. Good reasons to comment:

- **PRs:** summarise what the diff does and call out risks, missing tests, or
  CLAUDE.md / `ai/agents.md` / `ai/testing.md` violations (untagged Robot tests,
  `Optional` on DB dataclass fields, `[Return]` instead of `RETURN`, new files
  outside `src/rfc/` or `robot/`, missing type hints). Reference the project's
  own rules, by file.
- **Issues:** ask the one clarifying question that unblocks it, propose a
  concrete next step, or note the relevant code path (`file:line`).
- Keep comments short, specific, and actionable. No filler, no praise padding.
- Sign off implicitly via the marker; do not impersonate the owner's voice on
  decisions — propose, don't decree.

Never comment just to look busy. A labelled, well-triaged issue with no comment
is a perfectly good outcome.

## Escalation — what goes to the owner

Surface (in the run report, and by `human-in-the-loop` label) anything that:

- needs a close/merge/priority/scope decision,
- is contentious, security-sensitive, or involves a person dispute,
- contradicts CLAUDE.md or a documented decision,
- would exceed the safety rails to resolve.

## Reporting — always write a report

Each invocation writes a report so the owner can audit every action.

- **Heartbeat (cloud):** commit a markdown file to the `rfc-monitor-logs` repo
  at `heartbeat/YYYY-MM-DD/HHMM.md` (use the GitHub API / github MCP —
  `create_or_update_file` — since the cloud agent has no local checkout). Use the
  date/time from the run context.
- **Checkpoint (Actions):** the workflow writes to `checkpoints/`.
- **Listener (local):** append to `monitoring/logs/listener/<date>.md` in the
  local checkout.

Report contents: items seen, labels/assignees changed, comments posted (with
links), items deferred by the action cap, and the escalation list.
