# GitLab CI/CD Setup Guide for robotframework-chat

This guide explains how to set up GitLab CI/CD for running the Robot Framework test suite with Ollama models.

## Overview

The GitLab CI configuration (`./gitlab-ci.yml`) runs:
- Pre-commit checks (ruff, mypy)
- Robot Framework test suites (math, docker, safety)
- Model metadata research using Playwright
- Aggregated test reports with GitLab Pages support

## Prerequisites

### GitLab Runner Requirements

1. **GitLab Runner** with the following tags:
   - `ollama` - For runners with Ollama installed
   - `docker` - For runners with Docker-in-Docker support

2. **Hardware Requirements**:
   - Minimum 8GB RAM (16GB recommended)
   - 50GB disk space
   - Docker support (for Docker tests)

3. **Software**:
   - GitLab Runner (version 15.0+)
   - Docker
   - Ollama
   - Python 3.11+

## Setting Up a GitLab Runner

### Step 1: Install GitLab Runner

```bash
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install gitlab-runner

# Register with tags for Ollama
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
ollama pull mistral
ollama pull codellama
ollama list
```

## CI/CD Variables

Configure in GitLab (Settings > CI/CD > Variables):

| Variable | Description | Default |
|----------|-------------|---------|
| `OLLAMA_ENDPOINT` | Ollama API endpoint | `http://localhost:11434` |
| `DEFAULT_MODEL` | Default model | `llama3` |
| `ARTIFACT_RETENTION_DAYS` | Artifact retention | `30` |

## Artifacts

The CI collects:
- `log.html` - Detailed execution log
- `output.xml` - Test results (XML)
- `report.html` - Summary report
- `ci_metadata.json` - CI environment info

Access via:
1. Job page (Download artifacts)
2. GitLab Pages (if enabled)
3. GitLab API

## Runner Tagging

Use tags to specify model capabilities:

```bash
# Small models (7B-8B)
sudo gitlab-runner register --tag-list "ollama,small-model"

# Medium models (13B)
sudo gitlab-runner register --tag-list "ollama,medium-model"

# Large models (70B)
sudo gitlab-runner register --tag-list "ollama,large-model"
```

## Troubleshooting

### Ollama Not Available
```bash
curl http://localhost:11434/api/tags
sudo systemctl start ollama
journalctl -u ollama -f
```

### Model Not Found
```bash
ollama pull llama3
ollama list
```

### Memory Issues
- Increase runner RAM to 16GB+
- Use smaller models
- Run fewer parallel tests

## Model Metadata

The CI researches model metadata via Playwright:

```bash
robot -d results/metadata robot/ci/fetch_model_metadata.robot
```

This updates `robot/ci/models.yaml` with:
- Release dates
- Parameters
- Hardware requirements
- Capabilities

## Pre-Run Modifier

Dynamically configures tests based on available models:

```bash
robot --prerunmodifier rfc.pre_run_modifier:ModelAwarePreRunModifier tests/
```

Features:
1. Queries Ollama for available models
2. Reads model configuration
3. Filters tests by model availability
4. Adds CI metadata to results
