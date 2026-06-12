# CLAUDE.md — Claude Code instructions

This is the routing file: the always-loaded facts, rules, and pointers. Detailed
procedures live as skills under `.claude/skills/` (see § Skills); long-form
reference docs live under `ai/`.

- Read `ai/agents.md` for architecture, code style, and the agent contract.
- Read `ai/testing.md` for grading tiers and test rules.
- Read `ai/ROLES.md` for the four-role agent system (see § Role system).

---

## Working style: interview mode

**Before acting on any non-trivial task, stay in interview/plan mode.** Ask
focused questions, push back on assumptions, and understand the full picture
before proposing a plan. Don't implement until ambiguities are resolved, a clear
plan exists, and the user has confirmed it. When the prompt is specific and
unambiguous (e.g. "fix this typo"), just do it; when it's broad or has hidden
complexity, ask 2–4 focused multiple-choice questions first.

---

## Session startup

Every new session begins with a repo health check, before writing any code:

1. **Create a feature branch** from `claude-code-staging` — one branch per
   session, one session per feature:
   ```bash
   git fetch origin claude-code-staging
   git checkout -b claude/<short-description>-<random5> origin/claude-code-staging
   ```
2. **Pre-check the repo** — fix or ask before building on a broken baseline:
   ```bash
   uv run pytest
   pre-commit run --all-files
   make code-quality-check
   make robot-dryrun
   ```
3. **Scan for staleness:** check `humans/TODO.md`; look for `TODO`/`FIXME`/dead
   code in files you'll touch; flag findings to the user (fix now / defer /
   ignore).
4. **Ask clarifying questions** (see § Questions).

---

## Questions

Ask 2–4 multiple-choice questions before acting on any ambiguous or multi-step
task. Present concrete options, not open-ended prompts.

**Ask when:** the task touches > 3 files or crosses module boundaries; it could
be read multiple ways; scope is growing; you're making a directional decision
(API, naming, architecture); or something in the repo contradicts the request.

**Don't ask when:** the prompt is specific, unambiguous, and scoped to a single
file or function — just do it.

If a process isn't clear, ask. If CLAUDE.md, `ai/agents.md`, or `ai/testing.md`
could be improved, say so and propose a change.

---

## Core workflow

1. **TDD is mandatory.** Pair every feature or fix with a pytest update: write a
   failing test first, implement, then refactor.
2. **Resolve all errors** before committing — zero failures from the full
   verification suite (§ Pre-commit verification).
3. **Atomic commits.** One idea per commit: `<type>: <summary>` where type is
   `test:`, `feat:`, `fix:`, `refactor:`, `docs:`, or `chore:`.
4. **Never bundle unrelated changes** or mix formatting with logic.
5. **Follow external checklists when provided** — a user-supplied checklist
   (Rufus plan, TODO list) takes precedence over the default workflow.

---

## Pre-commit verification

Run **all** of the following before every commit (no exceptions unless the user
says to skip a step), then self-review `git diff --staged`:

```bash
uv run pytest                     # Python unit tests — must pass
pre-commit run --all-files        # Hooks: yaml, json, whitespace, ruff, mypy
make code-quality-check           # Lint (ruff) + typecheck (mypy)
make robot-dryrun                 # Validate Robot tests parse correctly
```

Self-review checklist: no changes outside intended scope; no debug prints or
commented-out code; no unresolved `TODO`/`FIXME`; no new files outside `src/rfc/`
(Python) or `robot/` (Robot tests); type hints on new Python; every Robot test
tagged `tier:*` + `verify:*`; no violations of `ai/agents.md` / `ai/testing.md`.
If something looks wrong, fix it or ask (fix now / leave / split).

---

## Branching and commits

Multiple agents may work on this repo simultaneously, so:

- **One branch per session:** `claude/<description>-<random5>`, created at
  session start. All work for the session goes on it. (Role-loop agents use
  `<type>/<issue-number>-<slug>` instead — see `ai/ROLES.md`.)
- **Rebase before pushing:**
  ```bash
  git fetch origin claude-code-staging
  git rebase origin/claude-code-staging
  ```
- **Small, atomic commits** — each independently reviewable, bisectable, and
  green on its own.
- **Never commit `uv.lock`.** It is gitignored; `pyproject.toml` pins versions.

---

## Rules

- `src/rfc/` is the single source of truth for all Python code.
- `robot/` is the single home for all Robot Framework tests.
- Type hints required on all new Python code. mypy must pass.
- Never use `Optional` for database dataclass fields — use concrete defaults.
- Use `RETURN` (not `[Return]`) in Robot Framework keywords.
- Every Robot test tagged with exactly one `tier:*` and one `verify:*` tag.
- New Robot test suites must be registered in `config/test_suites.yaml` and
  `config/local_models.yaml`.
- Always rebase onto `claude-code-staging`, not `main`.
- **Never commit `uv.lock`.** It is gitignored. Run `uv sync` to regenerate
  locally. `pyproject.toml` pins exact versions and is the source of truth.
- **Prefer skip-and-log over hard failure for optional / external dependencies.**
  When a CLI tool depends on an optional service (LLM endpoint, optional DB
  table, network resource), skip the affected unit (one model, one suite, one
  metric) with a clear log message and continue, rather than aborting the whole
  run. Hard-fail only when the work cannot meaningfully proceed (e.g., primary
  DB URL is unset). Always surface a final summary of what was skipped and why.

---

## Role system

This repo runs a four-role agent system defined in **`ai/ROLES.md`** — read it
before acting as a role. Role definitions live in `.claude/agents/`:

- `engineering` — loop: `status:ready` issues → pull requests
- `test-design` — loop: PRs → test plans → runs → verdicts + issues
- `project-management` — loop: triage → prioritize → quality review → monitoring
- `design` — open-ended: full-system awareness, RFCs, system-wide improvements

Start a role session with `claude --agent <role>` (or `@<role>` in-session).
All four roles may run concurrently: each works in its own git worktree with a
role-scoped identity per **`ai/GIT.md`** (worktree topology, sharing protocol,
submodule ownership) — required reading alongside `ai/ROLES.md`.
Role artifacts: test plans live in `ai/test-plans/`, RFCs in `ai/rfcs/`. The
label taxonomy and inter-role contract live in `ai/ROLES.md`; if it and a role
prompt conflict, `ai/ROLES.md` wins.

---

## Monitoring & dashboards

- CI: GitHub Actions — `gh run list` / `gh pr checks <number>`.
- Test results are archived to SQL and visualized in Apache Superset dashboards
  (see `ai/agents.md`).

---

## Refactoring

Refactoring is part of the workflow, not a separate activity:

| Trigger | Scope |
|---------|-------|
| **After completing a feature** | Refactor only the code you touched. |
| **After a version bump** | Broader cleanup — dead code, naming, structure. |
| **Session startup scan** | Flag dead code and staleness to the user. |
| **Spotted during work** | Ask before fixing. Don't silently clean up nearby code. |

For dead code removal, always ask first (remove / leave / add a TODO).

---

## Error recovery

When a check fails: **read the error** and understand the root cause; **fix if
obvious** (lint, type hints, trivial test failures) and re-run; **ask if not
obvious** after one attempt, stating what you tried and why it failed. Never loop
silently — if you've tried twice and it's still failing, escalate to the user.

---

## Skills

On-demand procedures live under `.claude/skills/`. Invoke (or let the model load)
the relevant one instead of keeping it in always-on context:

- **creating-prs** — the full PR workflow: rebase, verify, version bump, fill the
  PR template, create and monitor the PR.
- **reviewing-prs** — how to review a PR/branch (scope, tooling caveats, report
  structure). Use for `/review`.
- **running-robot-suites** — running real Robot suites, the 5-tuple watermark,
  and where output lands (Issue #350).
- **converting-tests** — migrate tests from other frameworks into the tiered
  system.
- **creating-tier0-tests** / **creating-tier1-tests** — author new Robot tests at
  the right tier.
- **importing-huggingface-data** — bring Hugging Face benchmarks in as test data.
- **rfc-worktree** — set up an isolated worktree for a fresh branch (manual:
  `/rfc-worktree`).
- **audit-robot-reports** — model × suite coverage audit from
  `make run-local-models`.

The **version-bump policy** lives in the creating-prs skill: default to a patch
bump per PR; minor for a new public keyword/API/suite; major for breaking
changes; skip for pure-docs or CI-only work.

---

## Environment

Copy `.env.example` to `.env` and edit before running integration tests. Key
variables: `OLLAMA_ENDPOINT`, `DEFAULT_MODEL`, `DATABASE_URL`. See `ai/dev.md` §
Environment Configuration for the full list.
