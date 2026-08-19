# Grading tiers & test rules

**Plain version — every test answers four questions:**

| Tag | Question | Example |
|---|---|---|
| `tier:*` | How hard is it to check? | `tier:0` pure Robot → `tier:4` Docker sandbox |
| `verify:*` | Who decides pass/fail? | `verify:python` code → `verify:llms` judge panel |
| `axis:*` | What one variable does it discriminate? | `axis:model` / `axis:harness` / `axis:prompt` / `axis:none` |
| `gold*` | Do we trust it enough to gate on? | `gold`, `platinum`, `gold:harness`, `platinum:harness` |

**Audience:** agents and humans maintaining tests.
**Authority:** owner-confirmed decisions from spec review.
Docs style: [writing.md](writing.md).

## The fundamental rule

**No test exists without a verification mechanism.** Robot Framework verifies
everything; every test carries a Robot or Python check.

- Deterministic checks live in Robot keywords (`Should Be Equal`, regex).
- Python-backed keywords are fine — but must surface pass/fail back into Robot.
- **LLMs never decide pass/fail alone.** Their output gets graded by Robot or
  Python logic.

## Grading Tiers

Tests are organized into tiers based on how verification is performed.

| Tier | Name                  | Description                                                              |
|------|-----------------------|--------------------------------------------------------------------------|
| 0    | Pure Robot            | Deterministic RF asserts only (`Should Be Equal`, regex).               |
| 1    | Robot + Python        | RF keywords backed by Python logic.                                     |
| 2    | Robot + LLM           | Single LLM grader evaluates the response.                               |
| 3    | Robot + LLMs          | 3+ grader models, majority vote. RF `WARN` on disagreement.            |
| 4    | Robot + LLMs + Docker | LLM output sandboxed in Docker, exit code checked.                      |
| 5    | Other                 | External graders, human-in-the-loop, hybrid.                            |
| 6    | None                  | Data collection only, no pass/fail.                                     |

### Tagging Rules

Every test case must declare its grading tier and verification style via tags:

- Tier tags: `tier:0`, `tier:1`, `tier:2`, `tier:3`, `tier:4`, `tier:5`, `tier:6`.
- Verification tags (recommended):
  - `verify:robot` — pure Robot asserts only (Tier 0).
  - `verify:python` — Robot + Python-backed keywords (Tier 1).
  - `verify:llm` — single LLM grader (Tier 2).
  - `verify:llms` — multi-LLM majority vote (Tier 3+).

Each test should have exactly one `tier:*` and exactly one `verify:*` tag.

Example:

```robot
*** Test Cases ***
Simple Math Should Be Deterministic
    [Tags]    tier:0    verify:robot
    Should Be Equal    ${RESULT}    42
```

### Axis tags

Beyond `tier:*`/`verify:*`, every suite declares exactly **one** `axis:*` tag
naming the single variable it is designed to discriminate — the *independent
variable* of the experiment, orthogonal to how the test is graded:

- `axis:model` — the LLM model (same prompt + harness, vary the model). Most
  eval suites.
- `axis:harness` — the coding-agent harness (claude-code / opencode / codex),
  the model held constant. The `harness_matrix` and harness-plumbing suites.
- `axis:prompt` — a prompt / template version (a prompt A/B).
- `axis:none` — pure code: no model, harness, or prompt in the loop (config /
  DB / BI plumbing, deterministic keyword-library behavior).

A discriminating test varies exactly one axis and holds everything else
constant, so a moving scoreboard cell can be attributed to that one variable
(RFC-008). `tier`/`verify` describe the grading *mechanism*; `axis` names the
*independent variable* — a `tier:2 verify:llm` eval is `axis:model`, while a
`tier:4` harness suite that also drives an LLM is `axis:harness` (the model is
held constant, the harness varies). The tag lives on the suite (`Test Tags` /
`Force Tags`) or on an ancestor `__init__.robot`, which cascades it to every
child suite.

`modules/ops/scripts/check_test_axes.py` checks this mechanically from each
suite's transitive `Library`/`Resource` import surface: a suite that imports an
LLM or harness keyword library may not claim `axis:none`, and a declared
`axis:harness`/`axis:model` must match the surface it exercises (`axis:prompt`
is a data variation and has no import signature). It runs in **enforce** mode —
every suite must carry exactly one axis tag or CI fails (a hard gate, like
`check_rfc_index.py`); it shipped in report mode during the RFC-008 A1→A4
backfill window (#243). Which
model digest, prompt hash, or harness version *actually ran* is runtime
provenance recorded in the spine, never in a static tag: a static tag says a
suite discriminates the harness axis, not which harness ran. Legacy provenance
tags (`harness:*`, `agent:*`, `prompt:*`) remain usable as `--include` filters
but are no longer the provenance record.

### Graded test pools (`gold` / `platinum`)

`tier`/`verify`/`axis` describe what a test *is*. A **graded pool** tag says how
much we *trust* it — which tests are good enough to gate on. Two pools exist,
deliberately namespaced so a gate filter for one never selects the other:

| Pool | Tags | Axis | Consumer |
|---|---|---|---|
| Model | `gold`, `platinum`, `stress` | `axis:model` | monorepo RSI gate (`--include gold --exclude stress`) |
| Harness | `gold:harness`, `platinum:harness` | `axis:harness` | `make robot-gold` / `make robot-platinum` |

The bare tags are **owned by the model pool** (commit `0f95f75`). Do not reuse
them for a harness suite: the RSI gate's existing `--include gold` would
silently start pulling harness suites into the model gate — a graded pool whose
membership can change by accident is not a gate.

`platinum` / `platinum:harness` marks the single highest-signal test in its
pool. It **always runs**, on every gate, no exceptions. `stress` marks a
latency-bound member the quality gate excludes while keeping it in the pool.

#### What earns a gold tag

A test is gold only if it clears all five:

1. **Discriminating** — the axis's values actually disagree on it. A test
   everything passes measures nothing.
2. **Deterministically graded** — `verify:robot` or `verify:python`. No LLM
   judge in the gate path: judge variance is not the variance you are measuring.
3. **Attributable** — brackets a spine session, so the result carries its
   runtime coordinate (model id + digest, or harness name + version).
4. **Cheap in replay** — ~0 tokens under `RFC_RUN_MODE=replay`, with
   `replay_of_recording_id` stamped so a replayed green is never mistaken for a
   live pass.
5. **Non-vacuous** — cannot pass on empty input. A run that emitted no commands
   must fail, not pass silently (the #385 / #390 / #402 lesson).

Plus one **set-level** rule: at least two members must be *negative controls*
tagged `control:instrument` — tests that assert the instrument goes RED on a
deliberately planted defect. A green pool proves nothing if nothing in it can
fail.

#### Membership is pinned, not implied

The harness pool is registered in `config/gold_harness.yaml` and enforced by
`scripts/check_gold_suites.py` (`make gold-check`, also run as a pytest in
`tests/test_check_gold_suites.py`). Membership is keyed on `(suite, test)`, so
a rename, a deletion, or a drive-by tag edit fails CI in both directions:

- a pinned member that lost its tag → **missing**
- a test that gained the tag without being added → **untracked**

Adding or removing a member is a reviewable change to the manifest, with a
`why:` line. This is the same "prompts request, checks enforce" discipline
`check_test_axes.py` applies to `axis:*`.

### Tier Expectations

- **Tier 0 – Pure Robot**
  - Only deterministic Robot asserts.
  - No LLM calls, no non-deterministic behavior.

- **Tier 1 – Robot + Python**
  - Robot keywords may call Python functions.
  - Python must return clear pass/fail back to Robot.
  - **`verify:python` checks STRUCTURE, not CONTENT (owner-confirmed scope cap).**
    A tier:1 verifier reasons over a *normalized artifact* (e.g. an `AgentRun`:
    command tokens, exit codes, changed *paths*). It guarantees STRUCTURAL
    properties and nothing more. The complex-workflow verifiers in
    `src/rfc/agent_verifiers.py` are the canonical example: they guarantee
    **structural commit-gating** — operator-aware effective status (an
    `&&`/`||`/`;`/`|`/`&` chain's exit code is interpreted, not assumed), a
    drop-a-side fragment denylist for conflict resolutions, and tokenized
    command identity for the load-bearing verbs (`git commit`,
    `git checkout <sha>`).
  - A tier:1 verifier is **not a shell interpreter and does not certify
    worktree contents.** The following are explicitly OUT OF SCOPE at tier:1
    and are deferred to the **tier:4 sandbox pilot (#390)**, which can diff the
    actual worktree against the contract:
    - arbitrary shell-grammar evasion — e.g. pathspec checkout without `--`,
      `echo` of a gating needle, abbreviated/prefix revision resolution,
      rebase-continuation tokenizing beyond the current denylist, background
      `&` content effects;
    - content-level claims — "both conflict sides were preserved", "the
      upstream change was actually applied";
    - live-runner per-command capture nuances — fixture wording for runners
      that do not inject the scenario event.
  - Rationale: widening a tier:1 denylist/tokenizer to chase arbitrary shell
    grammar is a runaway loop with no fixed point. Structural commit-gating is
    guaranteed at tier:1; content/grammar verification is a tier:4 (#390)
    concern by design.

- **Tier 2 – Robot + LLM**
  - One LLM grader receives model output and returns a grade.
  - Robot converts that grade to PASS/FAIL.

- **Tier 3 – Robot + LLMs**
  - Three or more grader models evaluate the same output.
  - Robot computes majority vote, fails on negative consensus, and emits `WARN` if graders disagree.
  - **Avoid self-grading bias.** Judges must be distinct from the generation model. Each pipeline that uses a panel reads its model list from a dedicated env var (e.g. `CEO_GRADER_MODELS`, `CREATIVITY_GRADER_MODELS`); when the var is unset the test skips (`ROBOT_SKIP`) rather than silently reusing the generation client. See issue #260 for the rationale.

- **Tier 4 – Robot + LLMs + Docker**
  - Same as Tier 3, but candidate outputs are executed in a sandboxed Docker container.
  - Exit code and runtime checks become part of the grading signal.

- **Tier 5 – Other**
  - Hybrid or external grading mechanisms (e.g. human review tools).
  - Robot still records the final pass/fail.

- **Tier 6 – None (Data collection)**
  - Runs prompts and records responses without pass/fail.
  - Reserved for exploratory data; avoid using this tier for production-quality suites.

## Implementation Guidance

- Implement **Tier 0–1 first**; they are the foundation for higher tiers.
- Shared grading keywords (single-LLM and multi-LLM) should live in common Robot resources and be used only by tests tagged with the appropriate tier.
- Meta-tests or CI scripts should enforce that every test has valid `tier:*` and `verify:*` tags and that Tier 0–1 suites do not import LLM grading keywords.

## Agent Workflow Tests

Agent workflow tests capture multi-turn agent execution as a structured
`AgentWorkflow` and assert against it with Python-backed keywords. See
`robot/30__tier3/agent_workflows/README.md` for the full guide.

- **Synthetic suites** (mock messages and tool results) are `tier:1
  verify:python` — fast, deterministic, run on every CI build.
- **Live-LLM suites** (real model invocation, Python-graded shape) are
  `tier:3 verify:python` — gated on `Verify LLM Available`, run nightly.

When the `AgentWorkflowListener` is attached, finalised workflows are
persisted to the configured database so historic agent runs become
queryable alongside test results.

## Suite Privacy Routing (#512)

Every suite entry in `config/local_models.yaml` may declare a `privacy`
field: `public` (the default when absent) or `local-only`.

- `public` suites may be scheduled anywhere, including free external
  providers (OpenRouter `:free`, Groq, Cerebras, Google AI Studio).
- `local-only` suites never reach an external provider unless that
  provider sets `allow_local_only: true` — reserved for paid endpoints
  with a zero-data-retention agreement. Violations are a hard skip with
  a log line, not a failure.
- Unknown `privacy` values fail closed: the suite is treated as
  local-only, so a typo can never leak a proprietary suite to a
  train-on-data endpoint.

Mark a suite `local-only` the moment proprietary content enters it —
the guard is mechanical protection, not memory.

## Comparing across dependency arms

When comparing skip/pass counts across dependency arms, run an exact
`uv sync --extra ...` for each arm before `pytest`. `uv run --extra X pytest`
does **not** prune extras already present in the venv, so a fat `.venv`
silently hides skips and yields false comparisons (design's #291 ruling).

---

For Make targets and local workflows, run `make help`.
