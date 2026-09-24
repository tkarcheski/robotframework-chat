# CLAUDE.md: how to work in this repo

**Plain version:**

- This repo tests LLMs and coding agents like software. Robot Framework runs the
  tests, Python does the logic, results go to SQL and Superset.
- **Ask before you build.** Broad task → 2-4 multiple-choice questions first.
- **Test first, always.** Failing pytest → code → refactor.
- **Red CI blocks everything.** No exceptions, including failures you inherited.
- **One branch per session**, off `claude-code-staging`, never `main`.

Detail below. Docs style: [ai/writing.md](ai/writing.md).

**Where things live:**

| Need | Read |
|---|---|
| Architecture, code style, agent contract | `ai/agents.md` |
| Grading tiers, tags, test rules | `ai/testing.md` |
| Step-by-step procedures | `.claude/skills/` (see § Skills) |
| Long-form reference | `ai/` |

---

## Working style: interview mode

**Don't build until the ambiguity is gone.**

Broad or multi-step task → stay in plan mode. Ask focused questions, push back
on assumptions, get the plan confirmed.

Specific and unambiguous ("fix this typo") → just do it.

---

## Questions

Ask 2-4 **multiple-choice** questions before acting on anything ambiguous.
Concrete options, not open-ended prompts.

**Ask when:**

- It touches > 3 files or crosses module boundaries
- It could be read more than one way
- Scope is growing
- It's a directional decision (API, naming, architecture)
- Something in the repo contradicts the request

**Don't ask when:** the prompt is specific, unambiguous, and scoped to one file
or function. Just do it.

**New idea from the owner**: a feature or epic not yet on the board? Default
first move is a clarification round: 3-4 decision-shaping questions (scope,
consumers, priorities, constraints). Iterate until the owner confirms clarity or
says to proceed with defaults. *Then* dispatch work.

Refinements to already-tracked work use judgment, not the full round.

If a process isn't clear, ask. If `CLAUDE.md`, `ai/agents.md`, or `ai/testing.md`
could be better, say so and propose the change.

---

## Session startup

Repo health check before any code:

**1. Branch**: one branch per session, one session per feature.

```bash
git fetch origin claude-code-staging
git checkout -b claude/<short-description>-<random5> origin/claude-code-staging
```

**2. Pre-check**: fix or ask before building on a broken baseline.

```bash
uv run --extra dev --extra superset --extra swebench pytest
pre-commit run --all-files
make code-quality-check
make robot-dryrun
```

**3. Scan for staleness**: open issues touching the same area, `TODO`/`FIXME`/
dead code in files you'll touch. Flag findings to the user (fix now / defer /
ignore).

**4. Ask clarifying questions** (see § Questions).

---

## Core workflow

1. **TDD is mandatory.** Failing pytest first, then implement, then refactor.
   Every feature and fix gets one.
2. **Zero failures before committing** (see § Pre-commit verification).
3. **Atomic commits.** One idea each: `<type>: <summary>` where type is `test:`,
   `feat:`, `fix:`, `refactor:`, `docs:`, or `chore:`.
4. **Never bundle unrelated changes**, and never mix formatting with logic.
5. **A user-supplied checklist wins.** A Rufus plan or TODO list from the user
   overrides this default workflow.

---

## Pre-commit verification

Run **all four** before every commit. No exceptions unless the user says to
skip a step.

```bash
uv run --extra dev --extra superset --extra swebench pytest   # must pass
pre-commit run --all-files        # yaml, json, whitespace, ruff, mypy
make code-quality-check           # ruff + mypy
make robot-dryrun                 # Robot suites parse
```

**Why the extras matter:** they match what CI syncs. Without them ~40
sqlalchemy/swebench-gated tests silently skip, so a bare `uv run pytest` is a
weaker gate than CI's.

Then self-review `git diff --staged`:

- [ ] Nothing outside intended scope
- [ ] No debug prints, no commented-out code
- [ ] No unresolved `TODO`/`FIXME`
- [ ] No new files outside `src/rfc/` (Python) or `robot/` (Robot tests)
- [ ] Type hints on new Python
- [ ] Every Robot test tagged `tier:*` + `verify:*` + `axis:*`
- [ ] No violations of `ai/agents.md` / `ai/testing.md`

Something looks wrong → fix it, or ask (fix now / leave / split).

---

## Branching and commits

Multiple agents work this repo at once, so:

- **One branch per session:** `claude/<description>-<random5>`, created at
  session start. All session work goes on it.
- **Rebase before pushing:**
  ```bash
  git fetch origin claude-code-staging
  git rebase origin/claude-code-staging
  ```
- **Always rebase onto `claude-code-staging`**, never `main`.
- **Small, atomic commits**: each independently reviewable, bisectable, and
  green on its own.
- **Never commit `uv.lock`.** It's gitignored. `uv sync` regenerates it;
  `pyproject.toml` pins exact versions and is the source of truth.

---

## Rules

### Red CI is an absolute blocker

**Never merge (or recommend merging) anything with failing tests or checks.**

- Never call a PR "ready" before **every** check has run and passed.
- **"Pre-existing failure" is not an excuse.** A red baseline blocks new work:
  fix it, or get the owner's explicit deferral, before building on it.
- Applies to generated PRs too (mirror publishes, automation). A publish PR with
  failing checks gets fixed at source and regenerated, never merged.

### Code layout

- `src/rfc/`: the single source of truth for all Python.
- `robot/`: the single home for all Robot Framework tests.
- Type hints required on all new Python. mypy must pass.
- **Never use `Optional` for database dataclass fields.** Use concrete defaults.
- Use `RETURN` (not `[Return]`) in Robot keywords.

### Test tagging

- Every Robot test: exactly one `tier:*` and one `verify:*`.
- Every Robot suite: exactly one **`axis:*`**: `axis:model` / `axis:harness` /
  `axis:prompt` / `axis:none`, naming the single variable it discriminates. A
  discriminating test varies exactly one axis.
- A suite importing an LLM or harness keyword library may **not** claim
  `axis:none`. `check_test_axes.py` enforces this.
- Graded pools (`gold`, `platinum`, `gold:harness`, `platinum:harness`,
  `control:instrument`) are pinned and enforced. See `ai/testing.md`
  § Graded test pools and `make gold-check`.

### Provenance: unattributable results don't count

Every runtime-bound axis goes in the spine for the run: model (id + digest),
prompt (id + content hash), harness (name + version), sampling params, grader
version.

**A result whose coordinate wasn't recorded is not a comparison signal.** The
scoreboard ignores it.

### Suite registration

- New Robot suites → `config/test_suites.yaml` (the canonical registry every
  suite appears in).
- **Model-parameterized** suites: the ones an `axis:model` sweep runs
  (`make run-local-models`) also go in `config/local_models.yaml`, the
  model-sweep / routing registry (see `ai/testing.md`).
- `local_models.yaml` membership is a *superset* of `axis:model` (it also
  carries provider/routing entries), so suites on other axes are **not**
  required to appear there.

### Optional dependencies: skip and log, don't hard-fail

A CLI depending on an optional service (LLM endpoint, optional DB table, network
resource) skips the affected unit (one model, one suite, one metric) with a
clear log message, and continues.

Hard-fail only when the work genuinely cannot proceed (e.g. the primary DB URL
is unset).

Always print a final summary of what was skipped and why.

---

## Foundation-green gate

**Owner-ordered 2026-07-15: no new work dispatches while any current-foundation
suite is red.** The strict form of the red-baseline rule: fix the reds first,
add nothing new until every suite is 100% green.

- **Three surfaces, all green.** The monorepo (core + ops suites on `main`), the
  public robotframework-chat mirror's CI, and open-tolkein's suite on its
  `baseline` branch (its default, since it has no `main`). All three, before any new
  work starts.
- **Blocked means everything but red-fixes.** While red exists anywhere, the
  only permitted fleet work is fixing those reds, plus an explicit in-session
  human-owner instruction to do specific work despite the gate (not the standing
  loop dispatch, not a CEO-layer dispatch). Review cycles on already-built
  non-red-fix PRs pause.
  - Reviewing, signing off on, and merging the red-fix PRs **is** permitted
    red-fix work. Otherwise the dual-sign-off gate would deadlock its own
    escape path.
- **A pending fix still blocks.** A red whose dual-signed fix only awaits the
  owner's merge keeps the fleet off new work until that merge lands and green is
  re-verified.
- **Verify post-merge.** Verification is the post-merge health check across all
  three surfaces. New work resumes only once it passes.

---

## Error recovery

**Never loop silently.**

1. **Read the error.** Understand the root cause.
2. **Obvious?** (lint, type hints, trivial test failure) Fix and re-run.
3. **Not obvious?** Ask after *one* attempt, stating what you tried and why it
   failed.
4. **Two attempts, still failing?** Escalate to the user.

---

## Refactoring

Part of the workflow, not a separate activity.

| Trigger | Scope |
|---------|-------|
| After completing a feature | Refactor only the code you touched |
| After a version bump | Broader cleanup: dead code, naming, structure |
| Session startup scan | Flag dead code and staleness to the user |
| Spotted during work | **Ask first.** Don't silently clean up nearby code |

Dead code removal: always ask (remove / leave / add a TODO).

---

## Monitoring & dashboards

CI is GitHub Actions: `gh run list`, `gh pr checks <number>`.

Test results archive to SQL and render in Superset (see `ai/agents.md`).

Superset health checks, for dashboard outages and PM sweeps:

```bash
docker compose ps --all                              # stopped/unhealthy services
curl -fsS "localhost:${SUPERSET_PORT:-8088}/health"  # API alive
psql $DATABASE_URL -c "SELECT MAX(timestamp) FROM test_runs"  # freshness (<48h)
make superset-diagnose                               # deep connectivity check
```

---

## Skills

On-demand procedures live in `.claude/skills/`. Load the relevant one instead of
keeping it in always-on context.

| Skill | Use it for |
|---|---|
| `creating-prs` | Full PR workflow: rebase, verify, version bump, template, monitor |
| `reviewing-prs` | How to review a PR/branch. Powers `/review` |
| `running-robot-suites` | Real suite runs, the 5-tuple watermark, where output lands (#350) |
| `converting-tests` | Migrate tests from other frameworks into the tiered system |
| `creating-tier0-tests` | New deterministic Robot test (no LLM, no Python) |
| `creating-tier1-tests` | New Robot test with a Python keyword library |
| `importing-huggingface-data` | Bring HF benchmarks in as test data |
| `rfc-worktree` | Isolated worktree for a fresh branch (manual: `/rfc-worktree`) |
| `audit-robot-reports` | Model × suite coverage audit from `make run-local-models` |

**Version-bump policy** lives in `creating-prs`: patch per PR by default; minor
for a new public keyword/API/suite; major for breaking changes; skip for
pure-docs or CI-only work.

---

## Environment

Copy `.env.example` to `.env` and edit before running integration tests.

Key variables: `OLLAMA_ENDPOINT`, `DEFAULT_MODEL`, `DATABASE_URL`. Full
annotated list is in `.env.example`.

---

## Ollama / `.env` setup

**Get this wrong and every test reports `FAILED` on a timeout.**

`.env` is git-ignored. It never leaves your machine.

### Minimum config

```bash
cp .env.example .env
```

| Variable | What it is | Notes |
|---|---|---|
| `LLM_PROVIDER` | `ollama` (default) or `openai` | Leave `ollama` for local runs |
| `OLLAMA_ENDPOINT` | Ollama server URL | `http://localhost:11434` same-host; `http://<lan-host>:11434` to offload |
| `DEFAULT_MODEL` | Model under test | Must already be pulled: `ollama pull <model>` |
| `OLLAMA_TIMEOUT` | Per-request HTTP budget, seconds | Default `5400` (90 min). Ceiling for one LLM response |
| `DATABASE_URL` | Where results archive | Optional for a dry run; required to persist |

### Never commit these

Local `.env` only. Never in issues, PRs, logs, or the public mirror.

- **`OPENAI_API_KEY`** and the other provider keys (`OPENROUTER_API_KEY`,
  `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GOOGLE_AI_STUDIO_API_KEY`) are billable
  secrets. Leave blank to skip that provider (the harness skip-and-logs).
- **`POSTGRES_PASSWORD`** / `DATABASE_URL`: change `changeme` before any shared
  or networked deployment.
- **`SUPERSET_SECRET_KEY`**, `SUPERSET_ADMIN_PASSWORD`: replace the
  placeholders.
- **`OLLAMA_ENDPOINT`** isn't a secret on a trusted LAN, but an Ollama server is
  **unauthenticated**, so never bind it to a public interface.

### The two timeouts must agree

**Invariant: `Test Timeout` >= `OLLAMA_TIMEOUT`.**

1. **`OLLAMA_TIMEOUT`** (env, default **5400s / 90 min**): HTTP read budget for
   *one* `generate()` call, cold model load included. Exceeded → surfaces as
   `requests.exceptions.ReadTimeout`.
2. **Robot `Test Timeout`** (per suite, in `*** Settings ***`): wall-clock for
   the *whole* test, which may make several LLM calls.

Get it backwards and Robot aborts the test as `FAILED` while the HTTP client is
still legitimately waiting on the model. It looks like "every test timed out"
even though the model would have answered.

Suite `Test Timeout` values are sized as a multiple of the 90-min HTTP budget
for exactly this reason. Keep them at or above `OLLAMA_TIMEOUT` if you tune
either.

### Sizing for your hardware

| Hardware | `DEFAULT_MODEL` | `OLLAMA_TIMEOUT` |
|---|---|---|
| Workstation GPU (24GB+) | `qwen3:32b` | `5400` (default) |
| Consumer GPU (8-16GB) | `qwen3:8b` or `qwen3:14b` | `5400` |
| CPU-only / laptop | `qwen3:4b` / `phi3:latest` | `5400`, prefer tier:0-1 suites |

**Every test fails on timeout?** The model is too big for the box. That's not
the timeout's fault. Drop to a smaller `DEFAULT_MODEL` first; raising the
timeout only makes you wait longer to fail.

**First test times out, rest pass?** Cold model load. Raise `OLLAMA_TIMEOUT`, or
pre-warm with `ollama run <model> ""`.

**Need more than 90 min per test** (large batch/multi-call suites)? Raise the
suite's `Test Timeout`, keeping it `>= OLLAMA_TIMEOUT`.

Confirm endpoint and model first: `curl $OLLAMA_ENDPOINT/api/tags` should list
`DEFAULT_MODEL`.

### Sanity-check without spending model time

```bash
make robot-dryrun      # parses suites (catches Test Timeout / variable errors)
uv run --extra dev --extra superset --extra swebench pytest   # no live LLM needed
```
