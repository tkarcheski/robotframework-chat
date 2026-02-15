# Pipeline Strategy

This document describes the pipeline architecture and model selection
strategy for robotframework-chat CI/CD.

---

## Pipeline Modes

There are three pipeline modes, all generated from
`config/test_suites.yaml` via `scripts/generate_pipeline.py`:

| Mode | Trigger | Purpose |
|------|---------|---------|
| **Regular** | Every push / MR | Smoke-test the system works with the smallest viable model |
| **Dynamic** | Manual play-button | Discover Ollama nodes on the network, enumerate models, run every (node, model, suite) combination |
| **Scheduled** | Hourly cron | Run the dynamic pipeline automatically for continuous coverage |

---

## Model Selection Strategy

### Regular pipeline: smallest viable model

The regular pipeline exists to verify that **the testing system itself works** —
not to evaluate model quality. For this reason it always runs on the smallest
model that can pass the test suites.

- **Current default:** `llama3` (set in `.gitlab-ci.yml` and `config/test_suites.yaml`)
- As test suites grow and require more capable responses, the default model
  is bumped to the **smallest model that satisfies all suites**
- The goal is fast feedback on code changes, not model benchmarking

### Dynamic and scheduled pipelines: test every model

The dynamic pipeline discovers all available Ollama nodes and their loaded
models, then runs every (node, model, suite) combination. This is where
actual model evaluation and comparison happens.

- Scheduled pipelines run hourly to catch model regressions over time
- Manual triggers let developers test specific models on demand
- Results are archived to SQL and visualized in Superset dashboards

### When to update the default model

Update `DEFAULT_MODEL` in `.gitlab-ci.yml` and `defaults.model` in
`config/test_suites.yaml` when:

1. A new test suite requires capabilities the current default lacks
2. The current default model is deprecated or unavailable
3. A smaller model becomes available that still passes all suites

Always pick the **smallest model that passes all regular-pipeline suites**.

---

## Pipeline Stages

```
sync → lint → generate → test → report → deploy → review
```

| Stage | Jobs | Notes |
|-------|------|-------|
| `sync` | `mirror-to-github` | Push mirror to GitHub |
| `lint` | `pre-commit`, `ruff-check`, `mypy-check` | Code quality gates (allow_failure) |
| `generate` | `generate-regular-pipeline`, `generate-dynamic-pipeline` | Produce child-pipeline YAML from `test_suites.yaml` |
| `test` | `run-regular-tests`, `run-dynamic-tests` | Execute generated child pipelines |
| `report` | (in child pipeline) | `rebot` merges output.xml, imports combined results to DB |
| `deploy` | `deploy-superset` | Update Superset stack on default branch |
| `review` | `claude-code-review` | AI code review + fix via Claude Code Opus 4.6 (label or manual) |

---

## Listeners

Every Robot Framework run in CI attaches all three listeners:

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives results to SQL (SQLite or PostgreSQL) |
| `rfc.ci_metadata_listener.CiMetadataListener` | Adds CI context (commit, branch, pipeline URL) |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamps every Ollama chat call |

---

## Configuration

All test suite definitions live in `config/test_suites.yaml`. This single
file drives both the dashboard UI and CI pipeline generation. Changes
propagate automatically — no manual YAML editing in `.gitlab-ci.yml` for
test jobs.

See [AGENTS.md](AGENTS.md) for the full project architecture.
