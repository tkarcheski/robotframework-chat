---
name: red-team-loop
description: >-
  Run one turn of the adversarial red-team loop that develops new novel tests:
  read coverage, pick the highest-value uncovered attack vector, scaffold a
  scenario, tailor it, and reconcile the catalog against disk. The loop's engine
  lives in rfc.adversarial_taxonomy / adversarial_catalog / adversarial_generator
  and is driven by `uv run python -m rfc.adversarial_cli` (or `make adversarial-*`).
when_to_use: >-
  Trigger when the user wants to develop new adversarial / red-team / abuse tests,
  asks "what attack surfaces are undercovered", "propose new adversarial
  scenarios", "run the red-team loop", "extend the harness adversarial suite", or
  when doing a periodic sweep to grow attack coverage across the taxonomy.
---

# The adversarial red-team loop

A taxonomy-driven loop for continuously developing novel adversarial tests. It
separates the two things test development needs: **structure** (which the engine
guarantees — correct wiring, tags, registration, honest coverage) and
**creativity** (which you supply — the actual attack payload). One turn of the
loop closes one gap in the attack space.

## The attack space

Every scenario names one coordinate in a three-axis taxonomy
(`rfc.adversarial_taxonomy`):

- **Surface** — what is attacked: `coding_harness`, `model_under_test`,
  `agentic_tool_use`, `multi_agent`.
- **Technique** — how: `encoding_evasion`, `instruction_override`,
  `roleplay_jailbreak`, `indirect_injection`, `tool_output_poisoning`,
  `social_framing`, `obfuscation`, `multi_step_chain`, `memory_poisoning`,
  `delegation_abuse`.
- **Objective** — the threat-actor goal: `secret_exfiltration`,
  `unsafe_repo_action`, `guardrail_bypass`, `task_hijack`,
  `system_prompt_extraction`, `privilege_escalation`, `persistence`,
  `supply_chain`.

`Surface` maps to the suite `axis:*` tag: `coding_harness` → `axis:harness`,
everything else → `axis:model`. Keep that mapping honest — the axis guard
(`scripts/check_test_axes.py`) enforces it.

## The four verbs (one loop turn)

```bash
make adversarial-coverage     # or: uv run python -m rfc.adversarial_cli coverage
make adversarial-propose      #      ... adversarial_cli propose --limit 5
uv run python -m rfc.adversarial_cli scaffold <scenario_id>
make adversarial-validate     #      ... adversarial_cli validate   (CI gate)
```

1. **coverage** — prints implemented/proposed counts, vector coverage %, a
   per-surface breakdown, the ranked frontier, and any drift. Start here.
2. **propose** — the highest-severity proposed scenarios (the backlog), each
   with its vector, grading, and kill-chain steps. Pick one.
3. **scaffold `<id>`** — for a `coding_harness` scenario, writes a valid,
   *passing* fixture (`task.yaml` + `run.yaml`) under the agentic-coding
   fixtures tree — the recorded agent RESISTS the bait. For other surfaces it
   prints a payload-row template to paste into the suite's variables file.
4. **validate** — reconciles catalog status against disk (implemented specs must
   have their artifact; proposed specs must not) and checks structural
   integrity. Exits non-zero on any drift; wire it into CI.

## Turning a scaffold into a real test

The scaffold is a correct skeleton, not a finished test. To complete a turn:

1. Add or find the `ScenarioSpec` in `rfc.adversarial_catalog` (status
   `PROPOSED`). A `multi_step_chain` must list ≥ 2 `kill_chain` steps.
2. `scaffold` it. For a harness scenario, **sharpen the `task` bait** in the
   fixture and set scenario-appropriate `changed_paths_after` on the safe
   commands. For a live scenario, paste the payload row and add a test case.
3. Grade it — see the `adversarial-scenario-authoring` skill for the exact
   verifier/keyword choices and registration steps.
4. Flip the spec's status to `IMPLEMENTED` and set its `artifact` path **in the
   same commit** that adds the artifact, so `validate` stays green.
5. Run the gate: `make adversarial-validate && make robot-dryrun` plus the unit
   tests for any new Python.

## Design principles the loop enforces

- **Honest coverage.** A vector counts as covered only when an `IMPLEMENTED`
  spec has a real artifact on disk. `validate` fails on any lie.
- **Deterministic where possible.** Prefer `coding_harness` fixtures graded
  structurally (tier:1) — they run in CI with no model and are always
  green-able. Live (`verify:llm`) variants add realism but skip without an LLM.
- **Both variants for depth.** A serious objective deserves a deterministic
  fixture *and* a live variant, so it is both CI-gating and realistic.
- **The frontier is the backlog.** `propose` never runs dry until every intended
  vector is implemented; keep adding proposed specs for new attack ideas.
