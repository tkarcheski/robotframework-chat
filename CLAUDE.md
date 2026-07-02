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
   session, one session per feature.
   - **Role sessions** (`claude --agent <role>`): follow `ai/GIT.md` instead of
     the command below — create or enter a worktree, branch named
     `<type>/<issue-number>-<slug>`, role identity set. `ai/GIT.md` takes
     precedence over this step; never branch in place in the main checkout.
   - **Plain (non-role) sessions:**
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

- **NEVER merge — or recommend merging — anything with failing tests or failing
  CI checks.** Red CI is an absolute blocker, no exceptions:
  - Never tell the owner a PR is "ready" or "merge = publish" before **every**
    check has run and passed.
  - "Pre-existing failure" is not an excuse. A red baseline blocks new work:
    fix the failure (or get the owner's explicit deferral) before building on it.
  - This applies to generated PRs too (mirror publishes, automation): a publish
    PR with failing checks gets fixed at source and regenerated — never merged.
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
- Superset health checks (run these when diagnosing a dashboard outage or in PM sweeps):
  ```bash
  docker compose ps --all                   # all stack services — check State/Status for stopped/unhealthy
  curl -fsS "localhost:${SUPERSET_PORT:-8088}/health"  # Superset API alive (honors SUPERSET_PORT)
  psql $DATABASE_URL -c "SELECT MAX(timestamp) FROM test_runs"  # data freshness (<48h when runs expected)
  make superset-diagnose                    # deep connectivity + pipeline check
  ```

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
Environment Configuration for the full list, and § "Ollama / `.env` setup"
below for the LLM-specific walkthrough.

---

## Ollama / `.env` setup

The LLM suites talk to an [Ollama](https://ollama.com) endpoint. Getting `.env`
right is the difference between a green run and every test reporting `FAILED`
on a timeout. `.env` is git-ignored — it never leaves your machine.

### Minimum viable config

```bash
cp .env.example .env
```

Then set, at minimum:

| Variable | What it is | Notes |
|---|---|---|
| `LLM_PROVIDER` | `ollama` (default) or `openai` | Leave `ollama` for local runs. |
| `OLLAMA_ENDPOINT` | URL of the Ollama server | `http://localhost:11434` on the same host; `http://<lan-host>:11434` to offload. |
| `DEFAULT_MODEL` | Model under test | Must already be pulled: `ollama pull <model>`. |
| `OLLAMA_TIMEOUT` | Per-request HTTP budget, seconds | Default `5400` (90 min). The ceiling for one LLM response. |
| `DATABASE_URL` | Where results are archived | Optional for a dry run; required to persist results. |

### Security-sensitive variables — do not commit real values

Keep these in your local `.env` only; never paste them into issues, PRs, logs,
or the public mirror:

- **`OPENAI_API_KEY`** and the other provider keys (`OPENROUTER_API_KEY`,
  `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GOOGLE_AI_STUDIO_API_KEY`) — billable
  secrets. Leave blank to skip that provider (the harness skip-and-logs).
- **`POSTGRES_PASSWORD`** / `DATABASE_URL` — change `changeme` before any shared
  or networked deployment.
- **`SUPERSET_SECRET_KEY`**, `SUPERSET_ADMIN_PASSWORD` — replace the placeholders.
- **`OLLAMA_ENDPOINT`** is not a secret on a trusted LAN, but an Ollama server is
  **unauthenticated** — never bind it to a public interface.

### Timeouts: the two budgets and why they must agree

There are two independent timeouts on the LLM path, and on slow hardware they
must not fight each other:

1. **`OLLAMA_TIMEOUT`** (env, default **5400s / 90 min**) — the HTTP read budget
   for a *single* `generate()` call, cold model load included. Surfaces as
   `requests.exceptions.ReadTimeout` when exceeded.
2. **Robot `Test Timeout`** (per suite, in `*** Settings ***`) — wall-clock for
   the *whole* test, which may make several LLM calls.

**Invariant: `Test Timeout` >= `OLLAMA_TIMEOUT`.** If the test timeout is the
smaller of the two, Robot aborts the test as `FAILED` while the HTTP client is
still legitimately waiting on the model — which looks like "every test timed
out" even though the model would have answered. The suite `Test Timeout` values
are sized as a multiple of the 90-min HTTP budget for exactly this reason; keep
them at or above `OLLAMA_TIMEOUT` if you tune either.

### Recommended values for slow / local hardware

| Hardware | `DEFAULT_MODEL` | `OLLAMA_TIMEOUT` |
|---|---|---|
| Workstation GPU (24GB+) | `qwen3:32b` | `5400` (default) |
| Consumer GPU (8–16GB) | `qwen3:8b` or `qwen3:14b` | `5400` |
| CPU-only / laptop | `qwen3:4b` / `phi3:latest` | `5400`, and prefer tier:0–1 suites |

Tuning rules of thumb:

- **Every test FAILS on timeout?** The model is too big for the box before it's
  the timeout's fault. Drop to a smaller `DEFAULT_MODEL` first; raising the
  timeout only makes you wait longer to fail.
- **First test in a suite times out, rest pass?** That's cold model load. Raise
  `OLLAMA_TIMEOUT`, or pre-warm with `ollama run <model> ""` before the run.
- **Need a longer per-test budget than 90 min** (large batch/multi-call suites):
  raise the suite's `Test Timeout`, keeping it `>= OLLAMA_TIMEOUT`.
- Confirm the endpoint and model first: `curl $OLLAMA_ENDPOINT/api/tags` should
  list `DEFAULT_MODEL`.

After editing `.env`, sanity-check the wiring without spending model time:

```bash
make robot-dryrun      # parses suites (catches Test Timeout / variable errors)
uv run pytest          # unit tests, no live LLM required
```
