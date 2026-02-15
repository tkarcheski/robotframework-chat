# GitLab CI/CD Setup Guide

This guide explains how to set up GitLab CI/CD for running the Robot Framework test suite with Ollama models, database archiving, and Superset deployment.

## Overview

The pipeline has five stages:

```
sync → lint → test → report → deploy
```

| Stage | Jobs | Purpose |
|-------|------|---------|
| **sync** | `mirror-to-github` | Mirrors repository to GitHub |
| **lint** | `pre-commit`, `ruff-check`, `mypy-check` | Code quality checks |
| **test** | `robot-math-tests`, `robot-docker-tests`, `robot-safety-tests` | Robot Framework test execution with database archiving |
| **report** | `aggregate-results` | Merge reports with `rebot`, import combined results to database |
| **deploy** | `deploy-superset` | Deploy/update Superset stack on target host |

### Pipeline Data Flow

```
test stage:  math ─────────┐   docker ────────┐   safety ────────┐
             listener→DB   │   listener→DB    │   listener→DB   │
             (per-suite)   │   (per-suite)    │   (per-suite)   │
                           ▼                  ▼                 ▼
report stage:          rebot merges output.xml files
                           │
                           ├── results/combined/report.html  (one unified report)
                           ├── results/combined/log.html
                           └── import → DB  (pipeline-level combined run)
```

## Listeners

Every test job runs with both listeners attached:

```yaml
script:
  - uv run robot -d results/math
      --listener rfc.db_listener.DbListener
      --listener rfc.git_metadata_listener.GitMetaData
      robot/math/tests/
```

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives test runs and results to SQL database |
| `rfc.git_metadata_listener.GitMetaData` | Adds CI metadata (commit, branch, pipeline URL) from GitHub Actions or GitLab CI to Robot Framework output |

The `DbListener` uses `DATABASE_URL` when set, otherwise falls back to SQLite.

## Prerequisites

### GitLab Runner Requirements

1. **GitLab Runner** with the `ollama` tag for test jobs
2. **Hardware**: 8 GB RAM minimum (16 GB recommended), 50 GB disk
3. **Software**: Docker, Ollama, Python 3.11+, `uv`

### Step 1: Install GitLab Runner

```bash
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install gitlab-runner

sudo gitlab-runner register \
  --url https://gitlab.com/ \
  --token YOUR_TOKEN \
  --executor shell \
  --name "rfc-ollama-runner" \
  --tag-list "ollama"
```

### Step 2: Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl start ollama
sudo systemctl enable ollama
```

### Step 3: Pull Models

```bash
ollama pull llama3
ollama list
```

## CI/CD Variables

Configure in GitLab (Settings > CI/CD > Variables):

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `OLLAMA_ENDPOINT` | Ollama API endpoint | `http://localhost:11434` | No |
| `DEFAULT_MODEL` | Default LLM model | `llama3` | No |
| `DATABASE_URL` | PostgreSQL connection string | (unset → SQLite) | No |
| `GITHUB_USER` | GitHub username for mirroring | — | For sync stage |
| `GITHUB_TOKEN` | GitHub token for mirroring | — | For sync stage |
| `SUPERSET_DEPLOY_HOST` | Superset deploy target host | — | For deploy stage |
| `SUPERSET_DEPLOY_USER` | SSH user for deploy | — | For deploy stage |
| `SUPERSET_DEPLOY_PATH` | Path on deploy host | — | For deploy stage |

### Database Configuration

To archive test results to PostgreSQL (for Superset dashboards):

1. Set `DATABASE_URL` as a CI/CD variable:
   ```
   postgresql://rfc:password@postgres-host:5432/rfc
   ```
2. Both the `DbListener` (test stage) and `import_test_results.py` (report stage) will use it

When `DATABASE_URL` is not set, results are archived to local SQLite (`data/test_history.db`) and saved as artifacts.

## Report Stage

The `aggregate-results` job:

1. Collects `output.xml` files from all test jobs
2. Merges them with `rebot` into a single combined report
3. Imports the combined result into the database via `import_test_results.py`
4. Generates CI metadata JSON

```yaml
aggregate-results:
  script:
    # Merge with rebot
    - uv run rebot --name "Combined Results" --outputdir results/combined
        --output output.xml --log log.html --report report.html
        --nostatusrc $OUTPUT_FILES

    # Import combined results to database
    - uv run python scripts/import_test_results.py results/combined/output.xml --model "$DEFAULT_MODEL"
```

## Deploy Stage

The `deploy-superset` job runs only on the default branch when `SUPERSET_DEPLOY_HOST` is set. It SSHes into the target host and updates the Superset stack via `docker compose`.

Requirements:
- Runner must have SSH access to `$SUPERSET_DEPLOY_HOST`
- Target host must have Docker and `docker compose` installed
- Repository must be cloned on the target host at `$SUPERSET_DEPLOY_PATH`

## Artifacts

The pipeline produces:

| Artifact | Location | Description |
|----------|----------|-------------|
| Per-suite results | `results/{math,docker,safety}/` | Individual test output, log, report |
| Combined report | `results/combined/report.html` | Merged HTML report from all suites |
| Combined log | `results/combined/log.html` | Merged detailed log |
| Combined output | `results/combined/output.xml` | Merged XML output |
| CI metadata | `results/combined/ci_metadata.json` | Pipeline metadata JSON |
| SQLite database | `data/` | Local database (when DATABASE_URL is unset) |

## Troubleshooting

### Ollama Not Available

```bash
curl http://localhost:11434/api/tags
sudo systemctl start ollama
journalctl -u ollama -f
```

### No Output Files to Aggregate

If `aggregate-results` reports "No output.xml files found", check that test jobs produced artifacts. Test jobs use `allow_failure: true`, so the pipeline continues even when tests fail.

### Database Archiving Failures

The `DbListener` catches exceptions and logs warnings — it will not fail the test run if archiving fails. Check the Robot Framework log for messages like:

```
Failed to archive results to database: ...
```

### Memory Issues

- Increase runner RAM to 16 GB+
- Use smaller models
- Run fewer parallel tests
