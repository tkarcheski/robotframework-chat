# src/rfc/ — Python source

`src/rfc/` is the single source of truth for all Python code in this project.
Business logic lives here, never in `tests/` or `robot/`.

## Rules

- Type hints required on every function signature. `mypy` must pass.
- Never use `Optional` for database dataclass fields — use concrete defaults.
- Robot keyword libraries set `ROBOT_LIBRARY_SCOPE` (`SUITE` by default; `TEST`
  only when each test needs a fresh instance).
- Every new keyword library needs a matching `tests/test_*.py`, written failing
  first (TDD).
- Prefer skip-and-log over hard failure for optional / external dependencies
  (LLM endpoints, optional DB tables, network resources); hard-fail only when the
  work cannot meaningfully proceed.

See `ai/agents.md` for the full architecture and code-style contract, and the
`creating-tier1-tests` skill for the keyword-library + pytest pattern.
