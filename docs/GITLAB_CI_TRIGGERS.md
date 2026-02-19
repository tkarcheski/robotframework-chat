# GitLab CI Triggers

How the robotframework-chat pipeline decides **when** and **what** to run.

**Audience:** Developers, CI/CD maintainers
**Last updated:** 2026-02-19

---

## Overview

GitLab CI evaluates `rules:` on every job to decide whether to include it in a
pipeline. The **trigger source** (`CI_PIPELINE_SOURCE`) and **branch context**
(`CI_COMMIT_BRANCH`, `CI_MERGE_REQUEST_IID`) determine which jobs run.

This project uses three trigger types:

| Trigger | GitLab variable | When it fires |
|---------|-----------------|---------------|
| **Branch push** | `CI_COMMIT_BRANCH` | Any `git push` to a branch |
| **Merge request** | `CI_PIPELINE_SOURCE == "merge_request_event"` | MR created, updated, or rebased |
| **Schedule** | `CI_PIPELINE_SOURCE == "schedule"` | Cron schedule (hourly) |

A fourth trigger — **tag push** — is used exclusively for PyPI releases
(see [Release Pipeline](#release-pipeline-tag-push) below).

---

## Branch Push Trigger

**What:** A pipeline created by pushing commits to any branch.

**When it fires:**
- `git push origin feature-branch`
- `git push origin main`
- Any branch, including `claude-code-staging` and `claude/*` session branches

**Rule syntax:**
```yaml
rules:
  - if: $CI_COMMIT_BRANCH
```

**Jobs that run on branch push:**

| Job | Stage | Purpose |
|-----|-------|---------|
| `lint` | lint | Pre-commit, ruff, mypy |
| `generate-regular-pipeline` | generate | Build smoke-test child pipeline |
| `run-regular-tests` | test | Execute smoke tests |
| `dashboard-pytest` | test | Python unit tests |
| `repo-metrics` | report | Only on default branch |
| `deploy-superset` | deploy | Only on default branch |

**Key behavior:**
- Runs on **every** branch, giving fast feedback on every push
- On the default branch (`main`), also triggers deploy and reporting jobs
- Uses the smallest viable model (`llama3`) for speed

---

## Merge Request Trigger

**What:** A pipeline created when a merge request is opened, updated, or rebased.

**When it fires:**
- Opening a new MR
- Pushing new commits to an MR source branch
- Rebasing an MR
- Re-running a pipeline from the MR page

**Rule syntax:**
```yaml
rules:
  - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Jobs that run on merge requests:**

| Job | Stage | Purpose |
|-----|-------|---------|
| `lint` | lint | Code quality gate |
| `generate-regular-pipeline` | generate | Build smoke-test child pipeline |
| `run-regular-tests` | test | Verify tests pass before merge |
| `dashboard-pytest` | test | Unit tests |
| `dashboard-playwright` | test | Browser self-tests |
| `repo-metrics` | report | Post metrics as MR comment |
| `opencode-review` | review | AI code review (when labeled `opencode-review`) |

**Key behavior:**
- MR pipelines include **more jobs** than branch pushes (Playwright, AI review)
- `repo-metrics` posts a comment on the MR with code quality metrics
- `opencode-review` only runs when the MR has the `opencode-review` label
- MR pipelines and branch pipelines can **both** fire for the same push;
  GitLab deduplicates when `workflow:rules` are configured

---

## Scheduled Trigger

**What:** A pipeline triggered by a cron schedule configured in
GitLab (CI/CD > Schedules).

**When it fires:**
- Hourly cron (configured in GitLab project settings)
- Can also be triggered manually from the Schedules page

**Rule syntax:**
```yaml
rules:
  - if: $CI_PIPELINE_SOURCE == "schedule"
```

**Jobs that run on schedule:**

| Job | Stage | Purpose |
|-----|-------|---------|
| `discover-nodes` | generate | Ping Ollama nodes, build live inventory |
| `generate-dynamic-pipeline` | generate | Full (node, model, suite) matrix |
| `run-dynamic-tests` | test | Execute every combination |

**Key behavior:**
- Scheduled pipelines run the **dynamic** pipeline — the full test matrix
- `discover-nodes` finds all online Ollama nodes and their loaded models
- The dynamic pipeline tests **every model on every node** for regression tracking
- Results are archived to SQL for Superset/Grafana dashboards
- Regular-pipeline jobs (lint, dashboard-pytest) do **not** run on schedule

---

## Release Pipeline (Tag Push)

**What:** A pipeline triggered by pushing a Git tag matching `v*`.

**When it fires:**
- `git tag v0.3.0 && git push origin v0.3.0`
- Only semantic version tags (`v*`) trigger the release jobs

**Rule syntax:**
```yaml
rules:
  - if: $CI_COMMIT_TAG =~ /^v/
```

**Jobs that run on tag push:**

| Job | Stage | Purpose |
|-----|-------|---------|
| `lint` | lint | Final quality gate |
| `dashboard-pytest` | test | Verify tests pass |
| `publish-pypi` | release | Build and upload to PyPI |

**Key behavior:**
- Tag pipelines are the **only** way to publish to PyPI
- The `publish-pypi` job builds a wheel and sdist, then uploads via `twine`
- Requires `TWINE_USERNAME` and `TWINE_PASSWORD` (or `PYPI_TOKEN`) as
  CI/CD variables (masked, protected)
- Runs **after** lint and tests pass — no broken releases

---

## Manual Triggers

Some jobs can be triggered manually via the GitLab UI play button:

| Job | When available |
|-----|----------------|
| `discover-nodes` | Any pipeline (play button) |
| `generate-dynamic-pipeline` | Any pipeline (play button) |
| `run-dynamic-tests` | Any pipeline (play button) |
| `opencode-review` | Any pipeline (play button) |
| `dashboard-playwright` | Any pipeline (play button) |

Manual jobs use `when: manual` with `allow_failure: true` so they don't
block the pipeline.

---

## Master DAG

The complete pipeline as a directed acyclic graph, showing all trigger
paths and job dependencies:

```
                        ┌─────────────────────────────────────────────────┐
                        │              TRIGGER SOURCE                     │
                        └──────┬──────────┬──────────┬──────────┬────────┘
                               │          │          │          │
                          branch push   MR event   schedule   tag push
                               │          │          │          │
                               ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE: lint                                                            │
│                                                                         │
│  ┌──────────┐                                                           │
│  │   lint   │◄──── branch push, MR event, tag push                      │
│  └──────────┘                                                           │
└─────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE: generate                                                        │
│                                                                         │
│  ┌───────────────────────┐      ┌─────────────────┐                     │
│  │ generate-regular-     │      │  discover-nodes  │◄── schedule/manual  │
│  │ pipeline              │      └────────┬────────┘                     │
│  └───────────┬───────────┘               │                              │
│              │                           ▼                              │
│   branch push, MR event      ┌──────────────────────┐                   │
│              │                │ generate-dynamic-    │◄── schedule/manual│
│              │                │ pipeline             │                   │
│              │                └──────────┬───────────┘                   │
│              │                           │                              │
└──────────────┼───────────────────────────┼──────────────────────────────┘
               │                           │
               ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE: test                                                            │
│                                                                         │
│  ┌──────────────────┐  ┌──────────────────────┐  ┌──────────────────┐   │
│  │ dashboard-pytest  │  │  dashboard-playwright │  │  run-regular-   │   │
│  │                  │  │  (MR, main, manual)   │  │  tests          │   │
│  └──────────────────┘  └──────────────────────┘  └──────────────────┘   │
│  ◄── branch, MR, tag        ◄── MR, main              ◄── branch, MR   │
│                                                                         │
│  ┌──────────────────┐                                                   │
│  │ run-dynamic-tests│◄── schedule/manual                                │
│  └──────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE: report                                                          │
│                                                                         │
│  ┌──────────────────┐                                                   │
│  │  repo-metrics    │◄──── MR event, default branch                     │
│  └──────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE: deploy                                                          │
│                                                                         │
│  ┌──────────────────┐                                                   │
│  │ deploy-superset  │◄──── default branch + SUPERSET_DEPLOY_HOST        │
│  └──────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE: release                                                         │
│                                                                         │
│  ┌──────────────────┐                                                   │
│  │  publish-pypi    │◄──── tag push (v*)                                │
│  └──────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE: review                                                          │
│                                                                         │
│  ┌──────────────────┐                                                   │
│  │ opencode-review  │◄──── MR event (label: opencode-review) / manual   │
│  └──────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Dependency Graph (needs:)

```
lint ─────────────────────────────────────────────────────── (no deps)
generate-regular-pipeline ────────────────────────────────── (no deps)
discover-nodes ───────────────────────────────────────────── (no deps)
generate-dynamic-pipeline ──── needs: discover-nodes ─────── (optional)
dashboard-pytest ─────────────────────────────────────────── needs: [] (no deps)
dashboard-playwright ─────────────────────────────────────── needs: [] (no deps)
run-regular-tests ─────────── needs: generate-regular-pipeline
run-dynamic-tests ─────────── needs: generate-dynamic-pipeline (optional)
repo-metrics ─────────────────────────────────────────────── needs: [] (no deps)
deploy-superset ──────────────────────────────────────────── (stage order)
publish-pypi ──────────────── needs: [lint, dashboard-pytest] (gate on quality)
opencode-review ──────────────────────────────────────────── (stage order)
```

---

## Trigger Matrix Summary

| Job | Branch Push | MR Event | Schedule | Tag Push | Manual |
|-----|:-----------:|:--------:|:--------:|:--------:|:------:|
| `lint` | x | x | | x | |
| `generate-regular-pipeline` | x | x | | | |
| `discover-nodes` | | | x | | x |
| `generate-dynamic-pipeline` | | | x | | x |
| `dashboard-pytest` | x | x | | x | |
| `dashboard-playwright` | | x | | | x |
| `run-regular-tests` | x | x | | | |
| `run-dynamic-tests` | | | x | | x |
| `repo-metrics` | main only | x | | | |
| `deploy-superset` | main only | | | | |
| `publish-pypi` | | | | x | |
| `opencode-review` | | labeled | | | x |

---

## CI/CD Variables for Releases

Configure in GitLab (Settings > CI/CD > Variables):

| Variable | Description | Required for |
|----------|-------------|--------------|
| `PYPI_TOKEN` | PyPI API token (masked, protected) | `publish-pypi` |
| `TWINE_USERNAME` | PyPI username (use `__token__` for API tokens) | `publish-pypi` |
| `TWINE_PASSWORD` | PyPI password or API token | `publish-pypi` |

Use **either** `PYPI_TOKEN` **or** the `TWINE_USERNAME`/`TWINE_PASSWORD` pair.
`PYPI_TOKEN` is preferred — the release script maps it to `TWINE_PASSWORD`
automatically.

---

## How to Create a Release

```bash
# 1. Bump version in pyproject.toml
# 2. Commit the version bump
git add pyproject.toml
git commit -m "chore: bump version to 0.3.0"

# 3. Tag and push
git tag v0.3.0
git push origin main --tags
```

The tag push triggers the release pipeline: lint -> test -> publish-pypi.

---

## See Also

- [ai/PIPELINES.md](../ai/PIPELINES.md) — Pipeline strategy and model selection
- [docs/GITLAB_CI_SETUP.md](GITLAB_CI_SETUP.md) — Runner setup and prerequisites
- [docs/CI_SYNC.md](CI_SYNC.md) — Pipeline result sync and data flow
