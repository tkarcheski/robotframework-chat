# Issue/PR monitoring system

Three layers over one shared policy ([`triage-issues-prs`](../.claude/skills/triage-issues-prs/SKILL.md))
that watch `tkarcheski/robotframework-chat` and triage + engage with issues and PRs.

| Layer | Runtime | Trigger | Built from |
|---|---|---|---|
| 1 — Heartbeat | Claude cloud (scheduled agent) | every 30 min | the `schedule` routine (see below) |
| 2 — Checkpoints | GitHub Actions | issue/PR webhook events | `.github/workflows/claude-checkpoints.yml` |
| 3 — Local listener | your machine | webhook events via `gh webhook forward` | this directory |

All three invoke the **same** `triage-issues-prs` skill, so behaviour (labels,
safety rails, idempotency, the 5-comment-per-sweep cap) is identical regardless
of which layer woke the agent. Reports land in the `monitoring/logs/` submodule
([`rfc-monitor-logs`](https://github.com/tkarcheski/rfc-monitor-logs)).

## Layer 1 — Heartbeat

An always-on Claude scheduled cloud agent runs every 30 minutes, sweeps all open
issues/PRs, triages + engages, and commits a report to
`monitoring/logs/heartbeat/`. Created via the `schedule` skill / routine — see
the activation summary the assistant provided. It is the backstop that catches
anything the event-driven layers miss, and it runs even when your machine is off.

## Layer 2 — Checkpoints (GitHub Actions)

`claude-checkpoints.yml` fires on issue/PR events and applies the `needs-review`
label — a quiet signal the heartbeat prioritises. It posts no comments. To get
*instant* inline review in CI, add an `ANTHROPIC_API_KEY` repo secret and
uncomment the `anthropics/claude-code-action` step in the workflow.

## Layer 3 — Local listener

Streams webhook events to your machine and (optionally) wakes a headless Claude
to triage/engage or push development progress.

```bash
# notify + log only (safe default)
./monitoring/gh-webhook-listener.sh

# let claude act on each event (see the security note below first)
MONITOR_AUTO_ACT=1 ./monitoring/gh-webhook-listener.sh
```

Run it persistently with the provided systemd user unit
([`claude-monitor.service`](./claude-monitor.service)).

**Prerequisites:** authenticated `gh`, the `gh webhook` extension (the launcher
installs it), `python3`, and — for `MONITOR_AUTO_ACT=1` — an authenticated
`claude` CLI.

### ⚠️ Security: prompt injection

Webhook payloads contain text written by anyone who can open an issue or comment.
With `MONITOR_AUTO_ACT=1` that untrusted text reaches a full-tool agent running
`--dangerously-skip-permissions`. The shared skill instructs the agent to treat
issue/PR/comment text as untrusted and never follow embedded instructions, but
that is mitigation, not a guarantee. Keep auto-act **off** unless you understand
and accept this exposure; the notify+log default is safe.
