## Summary

<!-- 1-3 sentences: what changed and why. Link the issue if applicable. -->

## How to review

<!-- Guide the reviewer. What should they focus on? What's the critical path? -->

**Start here:** <!-- e.g., "Read src/rfc/grader.py — the core logic change is in grade_answer()" -->

**Key changes:**
<!-- Bulleted list of the important files/functions, in review order -->
-

**What to ignore:** <!-- e.g., "The test file additions are mechanical — focus on the implementation" -->

## Evidence of testing

<!-- Paste actual command output. Reviewers should not have to trust "it works." -->

<details>
<summary>pytest output</summary>

```
<!-- paste: uv run pytest -->
```
</details>

<details>
<summary>pre-commit output</summary>

```
<!-- paste: pre-commit run --all-files -->
```
</details>

<details>
<summary>code-quality-check output</summary>

```
<!-- paste: make code-quality-check -->
```
</details>

<details>
<summary>robot-dryrun output</summary>

```
<!-- paste: make robot-dryrun -->
```
</details>

## Critical changes

<!-- If this PR changes public APIs, database schema, config formats, or CI
     behavior, explain the impact here. Otherwise write "None." -->

## Reflection (fill in before requesting review)

<!-- This is the human-in-the-loop gate. The owner is the sole merge gate; this
     section is how you hand them what they need to approve. Answer honestly —
     "we didn't need most of this" is a valid, valuable answer. -->

- **Did we build the right thing?** <!-- Restate the actual ask in your own words and confirm this diff matches it — not what you assumed. -->
- **Did we even need this?** <!-- Could it be smaller, or dropped entirely? What did you deliberately NOT add to avoid slop? -->
- **Evidence a human can see** <!-- Link the demo / paste the run output that proves it works end-to-end. "Trust me" is not evidence. -->
- **What would make this better?** <!-- One concrete improvement to the process, this template, or the approach for next time. -->

## Checklist

- [ ] All pytest tests pass
- [ ] pre-commit passes
- [ ] code-quality-check passes (ruff + mypy)
- [ ] robot-dryrun passes
- [ ] Self-reviewed diff — no scope creep, no debug prints
- [ ] Changes comply with `ai/agents.md` contract
- [ ] Changes comply with `ai/testing.md` tier rules
- [ ] New Robot tests have `tier:*` and `verify:*` tags
- [ ] No unresolved `TODO`/`FIXME` in changed files
- [ ] Type hints on all new Python code
- [ ] Commit history is atomic and bisectable
- [ ] Version bump confirmed with user (`pyproject.toml` + `src/rfc/__init__.py`)

## Sign-off gate (engineering PRs — both required before a human merges)

<!-- The reviewing roles set these, not the author. See modules/agents/ROLES.md rule 3. -->

- [ ] **test-design** signed off — `TEST-PLAN: PASS` + `signoff:test-design` label (coverage incl. integration verified)
- [ ] **design** signed off — `DESIGN: PASS` + `signoff:design` label (right thing, right shape, promotion-safe)
- [ ] `sign-off gate` CI check is green (both labels present, no stale verdict)
