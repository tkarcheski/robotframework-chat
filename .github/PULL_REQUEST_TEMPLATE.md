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
