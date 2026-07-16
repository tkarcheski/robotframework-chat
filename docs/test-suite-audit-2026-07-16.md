# Test Suite Audit — 2026-07-16

This audit inventories every Python test function discovered in the monorepo and gives each one a reason to keep it, a reason to remove or merge it, and a flag for whether it is strong enough to seed more variations. The exhaustive row-level audit lives in `core/docs/test-suite-audit-2026-07-16.csv`.

## Scope

- Audited test functions: **5103**.
- Variation issue seeds: **863** high-leverage tests.
- Discovery rule: every `test*.py` file outside `.git`, `node_modules`, `vendor`, and `__pycache__`, parsed with Python AST; every top-level or nested function whose name starts with `test`.
- Intent: support full end-to-end AI improvements by separating deterministic plumbing checks from harness, grader, replay, sandbox, provenance, and adversarial checks that should become richer scenario families.

## Portfolio by category

| Category | Tests | Audit posture |
|---|---:|---|
| unit/regression | 2874 | Keep while it documents a bug or contract; merge when it merely restates implementation details. |
| Robot keyword surface | 1167 | Keep for public keyword stability; merge repetitive parser cases into parametrized tables when readability suffers. |
| persistence/data contract | 462 | Keep for schema and replay integrity; remove only after migration-level tests cover old and new rows. |
| grader calibration | 263 | Keep as calibration anchors; remove only when a stronger golden dataset or jury replay absorbs the same cases. |
| configuration/provenance | 231 | Keep because AI improvements depend on reproducible provenance; remove stale config pins after deprecation windows. |
| end-to-end/integration | 106 | Keep aggressively; expand with provider, harness, and environment variants before removing lower-level coverage. |

## Portfolio by area

| Area | Tests |
|---|---:|
| `core/tests` | 4002 |
| `modules/ops` | 843 |
| `modules/nv-cache` | 124 |
| `modules/jury` | 99 |
| `modules/agents` | 14 |
| `modules/rfcs` | 14 |
| `core/robot` | 7 |

## Recommended issues to create
### Expand sandbox/live agent suites across harnesses
Use the rows flagged `create_variation_issue=yes` in agent sandbox, live runner, workflow, and verifier files to add provider/harness matrices plus failure-mode negative controls.

### Turn adversarial and injection tests into scenario families
Parameterize canary leakage, hidden instructions, tool hallucination, refusal, sycophancy, and semantic-cache adversaries with replay fixtures from real agent traces.

### Promote replay/provenance tests into end-to-end acceptance gates
For dialog replay, cache replay, git metadata, database listener, and model readiness tests, add full run-to-dashboard checks so AI improvement claims are traceable.

### Consolidate repetitive keyword parser tests without losing cases
Where dozens of small keyword tests share one parser, move inputs to tables/fixtures so the suite stays comprehensive but easier to audit weekly.

## Weekly repeat plan
Run this audit weekly and diff the CSV. New tests must include keep/remove rationale; deleted tests must name the broader test that absorbed the signal. The companion GitHub Actions workflow uploads the fresh audit as an artifact every Monday.

## How to use the CSV
- Filter `create_variation_issue=yes` to find tests worth expanding into issue-backed scenario families.
- Sort by `category` to identify duplicate parser/config tests that may be safe to merge.
- Use `reason_to_remove_or_merge` as the burden of proof before deleting any test.
