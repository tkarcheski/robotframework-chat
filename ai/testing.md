# Claude — Grading Tiers & Test Rules

**Audience:** AI agents and humans maintaining tests
**Authority:** Owner-confirmed decisions from spec review
**Last updated:** 2026-03-01

## Fundamental Rule

All tests are verified by Robot Framework. Every test must have Robot or Python checks. No test exists without a verification mechanism.

- Deterministic checks live in Robot keywords (e.g. `Should Be Equal`, regex).
- Python-backed keywords are allowed but must surface pass/fail back into Robot.
- LLMs never decide pass/fail alone; their outputs are graded by Robot or Python logic.

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

### Tier Expectations

- **Tier 0 – Pure Robot**
  - Only deterministic Robot asserts.
  - No LLM calls, no non-deterministic behavior.

- **Tier 1 – Robot + Python**
  - Robot keywords may call Python functions.
  - Python must return clear pass/fail back to Robot.

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
`robot/agent_workflows/README.md` for the full guide.

- **Synthetic suites** (mock messages and tool results) are `tier:1
  verify:python` — fast, deterministic, run on every CI build.
- **Live-LLM suites** (real model invocation, Python-graded shape) are
  `tier:3 verify:python` — gated on `Verify LLM Available`, run nightly.

When the `AgentWorkflowListener` is attached, finalised workflows are
persisted to the configured database so historic agent runs become
queryable alongside test results.

---

For Make targets and local workflows, see `humans/MAKE.md`.
