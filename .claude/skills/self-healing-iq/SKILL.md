---
name: self-healing-iq
description: >
  Closes the loop on the rfc self-healing listener: analyse and heal real
  suite failures, and ratchet difficulty upward (the IQ scale) for suites
  that always pass. Trigger when a robot suite fails repeatedly, when
  SelfHealingListener events show exhausted retries, when the coverage
  audit shows a suite at 100% pass across all models, or when the user
  says "self-heal this suite", "tests are too easy", "raise the IQ", or
  "why does this suite always pass".
---

# self-healing-iq

The active half of the self-healing system. The passive half already exists
in code (PR #373): the `@self_healing` decorator
(`src/rfc/self_healing.py`) retries failing LLM keywords with prompt
rewrites and parameter variations, emits `self_healing_*` RFC_DATA, and can
file GitHub issues when retries exhaust; `SelfHealingListener`
(`src/rfc/self_healing_listener.py`) collects those into
`SelfHealingEvent`s per test. This skill is what an agent does with that
signal — in both directions:

- **Failures → heal.** Diagnose and fix the root cause, never the symptom.
- **Permanent passes → escalate.** A suite that never fails measures
  nothing; raise its difficulty one notch (the IQ scale).

## Hard rules (both directions)

1. **Never weaken a test to make it pass.** Healing means fixing the
   prompt, fixture, keyword, environment, or model choice — not loosening
   an assertion, lowering a grading threshold, or deleting a test. A
   loosened assertion is a silent failure factory.
2. **One notch per PR.** Whether healing or escalating, change one
   difficulty variable at a time so the next run's delta is attributable.
3. **Evidence first.** Every heal/escalation PR quotes the listener events
   or coverage cells that justify it.
4. TDD and the full verification suite apply as always (CLAUDE.md).

## Direction 1 — Heal failures

### Gather the signal

```bash
# Which tests healed or exhausted retries in the last run?
# SelfHealingListener logs at suite end; events also land in output.xml
# as RFC_DATA (keys: self_healing_attempts, self_healing_strategy,
# self_healing_success, self_healing_original_prompt, ...).
uv run python - <<'EOF'
from robot.api import ExecutionResult
r = ExecutionResult("results/<version>/<model>/<suite>/<host>/<session>/output.xml")
# walk tests; print failures + any self_healing_* messages
EOF
```

Run the suite with the listener attached if the data is stale (see the
running-robot-suites skill for the 5-tuple watermark rules):

```bash
uv run robot --listener rfc.self_healing_listener.SelfHealingListener \
    --listener rfc.db_listener.DbListener -d results/heal-probe robot/<suite>/
```

### Classify, then fix at the right layer

| Signal | Root cause layer | Fix |
|---|---|---|
| `success=True` after N retries, same rewrite wins repeatedly | prompt | promote the winning rewrite into the suite's prompt/fixture permanently |
| retries exhausted, grader scores near threshold | grading | inspect grader transcript; fix grader prompt or expected-answer phrasing — NOT the threshold |
| exhausted, model output is garbage | model/env | wrong/too-small model for the suite; fix `config/local_models.yaml` pairing or skip-and-log that model |
| failures only on one host/node | environment | fleet problem (timeout, OOM) — fix infra, file issue, don't touch the test |
| decorator never fired | wiring | keyword isn't decorated or listener wasn't attached — fix the wiring |

The decorator already files GitHub issues on exhaustion
(`_create_github_issue`); before filing manually, search for its issue and
continue there (idempotency, same as the triage-issues-prs policy).

### Land it

Branch `claude/heal-<suite>-<random5>`, failing pytest first when the fix
touches `src/rfc/`, full verification suite, PR with the healing events
pasted as evidence.

## Direction 2 — The IQ scale (always-passing suites)

### Detect

A suite is **too easy** when the coverage audit (audit-robot-reports skill,
`.claude/audits/<date>-v<version>-coverage.md`) shows ✅ with ~100% pass
for that suite across **every** model on the fleet — including the small
ones — for two consecutive versions. A 3B model acing a reasoning suite is
a measurement failure, not a victory.

```bash
uv run python scripts/audit_robot_reports.py --audit-dir /tmp/iq-peek
# then read the matrix: suites whose every cell is ✅ are candidates
```

### Escalate exactly one notch

Pick the **lowest** rung that restores discrimination (some models fail,
strong models still pass):

1. **Harder instances** — swap/add fixture cases: longer inputs, more
   distractors, multi-step versions of the same task (e.g. via the
   importing-huggingface-data skill: pull a harder split).
2. **Tighter expected answers** — more precise phrasing demanded from the
   grader (without changing the numeric threshold).
3. **Adversarial phrasing** — reword prompts to remove telegraphed answers
   (the answer leaking into the question is the usual reason everything
   passes).
4. **Compound tasks** — chain two formerly separate assertions into one
   test (only after 1–3 failed to discriminate).

Never as escalation: raising grading thresholds globally, adding
flakiness/randomness, or timing-based difficulty — those add noise, not
signal.

### Verify the notch worked

Re-run the suite across at least 3 fleet models of different sizes
(running-robot-suites skill). Target outcome: the strongest model still
passes; at least one small model now fails for *content* reasons. If
everything still passes, take the next rung in a NEW PR. If everything
fails, you overshot — revert (this is the expected ~10% add-back, not a
defeat).

### Track it

- Tag escalated tests `iq:<n>` (n = notches above baseline, starting at
  `iq:1`) alongside the existing `tier:*`/`verify:*` tags so the audit can
  report difficulty drift over time.
- Note the escalation in the PR body: which rung, which models now fail,
  matrix cells before/after.

## Reporting

Either direction ends with the standard run report in the PR body: events
or matrix cells before → after, what was changed at which layer, and what
to watch in the next coverage audit.
