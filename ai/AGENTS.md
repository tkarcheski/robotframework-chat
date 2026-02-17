# Agent Instructions for robotframework-chat

A Robot Framework-based test harness for systematically testing LLMs.
Test results are archived to SQL and visualized in Apache Superset dashboards.

---

## Core Philosophy

1. **LLMs are software — test them like software.**
   They take input, produce output, and regress. They deserve the same CI,
   versioning, and regression discipline as any other software.

2. **Determinism before intelligence.**
   Structured, machine-verifiable evaluation first. Subjective or fuzzy scoring
   only after the deterministic foundation is solid.

3. **Constrained grading.**
   Graders return structured data only — scores, categories, pass/fail. No prose,
   no opinions, no unstructured output from the evaluation layer.

4. **Modular by design.**
   Start minimal, grow through composable pieces. New providers, graders, test
   types, and output formats plug in without rewriting core. Ollama today, any
   provider tomorrow.

5. **Robot Framework as the orchestration layer.**
   Tests are readable, keyword-driven, and framework-managed. Robot handles
   lifecycle, sequencing, and reporting — Python handles implementation.

6. **Every test run is archived.**
   Listeners are always active. Results flow to SQL. If it ran, it's queryable.

7. **CI-native, regression-focused.**
   Tests run in pipelines, gate deployments, and catch regressions. If it can't
   run unattended, it's not done.

---

## Agent Contract

**Rules:**
1. Write failing test first (red)
2. Implement minimal code (green)
3. Refactor if needed
4. Run code quality checks before committing:
   - `make code-format` — auto-format code with ruff
   - `make code-check` — run all quality checks (lint + typecheck)
   - `make code-coverage` — run pytest with coverage report
   - `pre-commit run --all-files` — final gate (yaml, json, whitespace, ruff, mypy)
5. Commit: `<type>: <summary>`

**Prohibited:**
- Skip tests
- Commit failing code
- Commit code that fails `make code-check`
- Bundle unrelated changes
- Mix formatting + logic
- Bypass pre-commit or Makefile quality checks

**Commit Types:**
- `test:` - Add/update tests
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code cleanup
- `docs:` - Documentation
- `chore:` - Maintenance

**Pull Request Workflow:**
1. Create feature branch from main
2. Implement changes following all rules above
3. Push branch to remote: `git push origin feature-name`
4. Create PR/MR with descriptive title and body
5. Monitor for feedback and respond promptly
6. Address review comments with additional commits
7. Update PR description if scope changes
8. Only merge after approval and all checks pass

---

## Commands

```bash
# Install
make install
# or: uv sync --extra dev --extra superset

# Install pre-commit hooks
pre-commit install

# Run tests
uv run pytest
uv run robot -d results robot/math
uv run robot -d results robot/docker/python
uv run robot -d results robot/safety

# Run specific test
uv run robot -d results -t "Test Name" robot/path/tests/file.robot

# Run by tag
uv run robot -d results -i IQ:120 robot/docker/python

# Run dashboard
uv sync --extra dashboard
rfc-dashboard  # or: uv run python -m dashboard.cli

# Code quality (prefer Makefile targets)
make code-format                # Auto-format with ruff
make code-lint                  # Run ruff linter
make code-typecheck             # Run mypy type checker
make code-check                 # Run all checks (lint + typecheck)
make code-coverage              # Run pytest with coverage
make code-audit                 # Audit dependencies for vulnerabilities

# Pre-commit (final gate)
pre-commit run --all-files
```

### Makefile Targets

```bash
make help          # Show all targets
make install       # Install dependencies (dev + superset)
make docker-up     # Start PostgreSQL + Redis + Superset
make docker-down   # Stop all services
make docker-restart # Restart all services
make docker-logs   # Tail service logs
make bootstrap     # First-time Superset setup
make robot         # Run all Robot Framework test suites
make robot-math    # Run math tests
make robot-docker  # Run Docker tests
make robot-safety  # Run safety tests
make import        # Import output.xml files: make import PATH=results/
make code-lint     # Run ruff linter
make code-format   # Auto-format code
make code-typecheck # Run mypy type checker
make code-check    # Run all code quality checks
make version       # Print current version

# CI targets (wrappers around ci/*.sh scripts)
make ci-lint                 # Run all CI lint checks
make ci-lint CHECK=ruff      # Run specific lint check
make ci-test                 # Run all tests with Ollama health check
make ci-test SUITE=math      # Run specific test suite
make ci-generate             # Generate regular child pipeline
make ci-generate MODE=dynamic # Generate dynamic child pipeline
make ci-report               # Generate repo metrics
make ci-report POST_MR=1     # Generate and post to MR
make ci-deploy               # Deploy Superset
make opencode-pipeline-review # Run OpenCode AI review in CI
make opencode-local-review   # Run OpenCode AI review on local changes
```

---

## Code Style

**Python:**
```python
# Imports: stdlib, third-party, local
import json
from dataclasses import dataclass
from robot.api import logger
from .models import GradeResult

# Naming
snake_case = "functions/variables"
PascalCase = "Classes"
UPPER_CASE = "CONSTANTS"
_leading_underscore = "private"

# Type hints required
def ask_llm(self, prompt: str) -> str:
    ...

# Error handling
except json.JSONDecodeError as e:
    raise ValueError(f"Invalid JSON: {raw}") from e
```

**Robot Framework:**
```robot
*** Settings ***
Documentation     Clear description
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Variables ***
${UPPER_CASE}     suite variables

*** Test Cases ***
Test Case Name
    [Documentation]    What this tests
    [Tags]    IQ:100    math
    ${answer}=    LLM.Ask LLM    ${QUESTION}
    Should Be Equal    ${answer}    ${EXPECTED}

*** Keywords ***
Custom Keyword
    [Arguments]    ${arg}
    [Documentation]    What this keyword does
    RETURN    ${result}    # Use RETURN, not [Return]
```

**Important Robot Framework Syntax:**
- Use `RETURN` (not `[Return]`) for keyword return values
- Define keywords in `*** Keywords ***` section before test cases
- Use `Suite Setup`/`Suite Teardown` for container lifecycle management
- Variables: `${scalar}`, `@{list}`, `&{dict}`

---

## Architecture

```
Robot Framework Test
│
├─> Python Keyword Library (src/rfc/)
│   ├─ Ollama Client (ollama.py) ── generation + model discovery
│   ├─ Grader (grader.py)
│   ├─ Safety Grader (safety_grader.py)
│   ├─ Docker Manager (container_manager.py)
│   ├─ Keywords (keywords.py, docker_keywords.py, safety_keywords.py)
│   ├─ Data Models (models.py) ── GradeResult, SafetyResult
│   ├─ CI Metadata (git_metadata.py) ── GitLab CI env collection
│   ├─ CI Metadata Listener (git_metadata_listener.py) ── attaches CI metadata to output
│   ├─ DB Listener (db_listener.py) ── archives results to SQL database
│   ├─ Ollama Timestamp Listener (ollama_timestamp_listener.py) ── timestamps Ollama chats
│   └─ Test Database (test_database.py) ── SQLite + PostgreSQL backends
│
├─> Listeners (auto-attached to every test run)
│   ├─ DbListener ── archives runs/results to SQL (SQLite or PostgreSQL)
│   ├─ GitMetaData ── adds CI context to Robot Framework output
│   └─ OllamaTimestampListener ── timestamps every Ollama chat call
│
├─> Docker Containers
│   ├─ Code Execution (Python, Node, Shell)
│   └─ LLM Services (Ollama)
│
├─> Superset Stack (docker-compose.yml)
│   ├─ PostgreSQL 16 ── test result storage
│   ├─ Redis 7 ── Superset cache
│   └─ Apache Superset 4.1.1 ── dashboards & visualization
│
└─> Test Results & Reports
    ├─ Robot Framework HTML reports
    ├─ SQL database (queryable history)
    └─ Superset dashboards (visualization)
```

---

## Project Structure

```
robotframework-chat/
├── readme.md                   # Project overview
├── ai/                         # AI agent documentation
│   ├── AGENTS.md               # Agent instructions (this file)
│   ├── SKILLS.md               # Agent capabilities
│   ├── DEV.md                  # Development guidelines
│   ├── PIPELINES.md            # Pipeline strategy & model selection
│   ├── REFACTOR.md             # Refactoring & maintenance guide
│   └── FEATURES.md             # Feature tracker (prioritized)
├── ci/                         # CI scripts (all pipeline logic lives here)
│   ├── common.yml              # Shared YAML templates
│   ├── lint.sh                 # Code quality checks
│   ├── test.sh                 # Test runner with health checks
│   ├── generate.sh             # Child pipeline generation
│   ├── report.sh               # Metrics and MR comments
│   ├── deploy.sh               # Superset deployment
│   └── review.sh               # Claude Code review
├── Makefile                    # Build, test, deploy, ci-* targets
├── docker-compose.yml          # PostgreSQL + Redis + Superset stack
├── .env.example                # Environment variable template
├── pyproject.toml              # Python dependencies + optional extras
├── src/rfc/                    # Python keyword library
│   ├── __init__.py             # Package version (__version__)
│   ├── ollama.py               # Ollama API client
│   ├── models.py               # Shared data classes
│   ├── git_metadata.py          # CI metadata collection
│   ├── git_metadata_listener.py # Listener: CI metadata → Robot output
│   ├── db_listener.py          # Listener: test results → SQL database
│   ├── ollama_timestamp_listener.py # Listener: timestamps Ollama chats
│   ├── test_database.py        # SQLite + PostgreSQL database backends
│   ├── keywords.py             # Core LLM keywords
│   ├── grader.py               # LLM answer grading
│   ├── safety_keywords.py      # Safety testing keywords
│   ├── safety_grader.py        # Regex-based safety grading
│   ├── docker_config.py        # Container configuration models
│   ├── container_manager.py    # Docker lifecycle management
│   ├── docker_keywords.py      # Docker container keywords
│   └── pre_run_modifier.py     # Dynamic model configuration
├── robot/                      # Robot Framework tests
│   ├── math/tests/             # Math reasoning tests
│   ├── docker/                 # Docker-based tests
│   │   ├── python/tests/       # Python code execution
│   │   ├── llm/tests/          # LLM-in-Docker tests
│   │   └── shell/tests/        # Shell/terminal tests
│   ├── safety/                 # Safety/security tests
│   └── resources/              # Reusable resource files
├── dashboard/                  # Dash-based test runner UI
├── superset/                   # Superset configuration
├── scripts/                    # Import/query/CI utilities
├── docs/                       # Additional documentation
│   ├── TEST_DATABASE.md        # Database schema & usage
│   └── GITLAB_CI_SETUP.md      # CI/CD setup guide
├── data/                       # SQLite database (gitignored)
├── results/                    # Test output (gitignored)
└── .pre-commit-config.yaml     # Git hooks
```

**Important:** `src/rfc/` is the single source of truth for all Python code.
`robot/` is the single home for all Robot Framework test suites. Never duplicate
logic outside of these directories.

---

## Listeners

Three Robot Framework listeners handle test result collection:

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives test runs and individual results to the SQL database (SQLite or PostgreSQL) |
| `rfc.git_metadata_listener.GitMetaData` | Collects GitLab CI metadata (commit, branch, pipeline URL, runner info) and adds it to test output |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamps every Ollama keyword call (Ask LLM, Wait For LLM, etc.) and saves `ollama_timestamps.json` |

All listeners are always active in the Makefile targets and in CI. Use them together:

```bash
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.git_metadata_listener.GitMetaData \
  --listener rfc.ollama_timestamp_listener.OllamaTimestampListener \
  robot/math/tests/
```

The `DbListener` reads `DATABASE_URL` from the environment to decide where to store results:

| `DATABASE_URL` | Backend | Notes |
|----------------|---------|-------|
| Not set | SQLite | Stores to `data/test_history.db` |
| `postgresql://...` | PostgreSQL | Requires `uv sync --extra superset` |

---

## CI/CD Pipeline

The GitLab CI pipeline uses a six-stage architecture with all logic
delegated to bash scripts in `ci/` and Makefile targets:

```
lint → generate → test → report → deploy → review
```

### Architecture: Minimal YAML, Modular Scripts

`.gitlab-ci.yml` is a bare-bones skeleton (~170 lines). It defines stages,
variables, rules, and artifacts — nothing else. All executable logic lives in:

| Layer | Location | Role |
|-------|----------|------|
| **Scripts** | `ci/*.sh` | Reusable bash scripts: lint, test, generate, report, deploy, review |
| **Templates** | `ci/common.yml` | Shared YAML templates (`.uv-setup`, `.robot-test`) |
| **Makefile** | `Makefile` | `ci-*` targets wrap scripts for local and CI use |
| **Python** | `scripts/generate_pipeline.py` | Generates child-pipeline YAML from `config/test_suites.yaml` |

To modify CI behavior, edit the scripts — not `.gitlab-ci.yml`.

### CI Scripts

| Script | Purpose | Makefile target |
|--------|---------|-----------------|
| `ci/lint.sh` | Run all linters, collect all failures, report summary | `make ci-lint` |
| `ci/test.sh` | Ollama health check + run test suites via Makefile | `make ci-test` |
| `ci/generate.sh` | Generate child pipeline YAML (regular/dynamic/discover) | `make ci-generate` |
| `ci/report.sh` | Repo metrics + MR comment posting | `make ci-report` |
| `ci/deploy.sh` | Deploy Superset stack to remote host | `make ci-deploy` |
| `ci/review.sh` | OpenCode AI review + pipeline fix (CI) | `make opencode-pipeline-review` |
| `ci/local_review.sh` | OpenCode AI review on local changes | `make opencode-local-review` |

All scripts follow these conventions:
- `set -euo pipefail` (fail fast)
- Source `.env` when present (auto-export via `set -a`)
- Verbose output on failure (diagnostics, paths, troubleshooting hints)
- Validate required env vars before proceeding
- Runnable locally: `bash ci/lint.sh` or `make ci-lint`

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

During the **test stage**, each suite runs with all listeners attached. The `DbListener` archives per-suite results to the database as each job completes.

During the **report stage**, `rebot` merges all `output.xml` files into a single combined report, and the combined results are imported into the database as a pipeline-level run.

During the **deploy stage** (default branch only), the Superset stack is deployed/updated on the target host.

During the **review stage** (MR label `opencode-review` or manual trigger), OpenCode (Kimi K2.5 via OpenRouter) inspects the pipeline for failed jobs, attempts to generate and apply fixes, then reviews the full MR diff against `ai/AGENTS.md` and `ai/REFACTOR.md`.

---

## Database

Test results are stored in a SQL database with dual-backend support:

- **SQLite** (default) — zero-config, stores in `data/test_history.db`
- **PostgreSQL** — for production use with Superset visualization

Set `DATABASE_URL` in your environment or `.env` to switch backends:

```bash
# PostgreSQL (for Superset)
DATABASE_URL=postgresql://rfc:changeme@localhost:5432/rfc

# SQLite (default when DATABASE_URL is unset)
```

See [../docs/TEST_DATABASE.md](../docs/TEST_DATABASE.md) for schema details, queries, and maintenance.

---

## Environment Configuration

All runtime settings live in `.env` (copied from `.env.example`). The file is
loaded at multiple layers so the same values propagate everywhere:

| Layer | How `.env` is loaded |
|-------|---------------------|
| **Makefile** | `-include .env` + `export` (lines 8-10) |
| **CI scripts** (`ci/*.sh`) | `set -a; source .env; set +a` (conditional) |
| **Python tests** (pytest) | `python-dotenv` via session fixture in `conftest.py` (`override=False`) |
| **suite_config.py** | `load_config()` overlays env vars onto YAML values |
| **Docker Compose** | Native `${VAR:-default}` interpolation |

### Env var → YAML config overrides

`load_config()` in `src/rfc/suite_config.py` applies these env var overrides
after loading `config/test_suites.yaml`:

| Env var | YAML path | Example |
|---------|-----------|---------|
| `DEFAULT_MODEL` | `defaults.model` | `mistral` |
| `OLLAMA_ENDPOINT` | `defaults.ollama_endpoint` | `http://gpu1:11434` |
| `GITLAB_API_URL` | `monitoring.gitlab_api_url` | `https://gitlab.example.com` |
| `GITLAB_PROJECT_ID` | `monitoring.gitlab_project_id` | `42` |

Empty env vars are ignored (YAML defaults are preserved). The `OLLAMA_NODES_LIST`
env var is handled separately by `dashboard/monitoring.py::_node_list()`.

---

## Docker Testing

**Container Profiles** (`robot/resources/container_profiles.resource`):
- `MINIMAL` - 0.25 CPU, 128MB RAM
- `STANDARD` - 0.5 CPU, 512MB RAM
- `PERFORMANCE` - 1.0 CPU, 1GB RAM
- `NETWORKED` - Bridged network
- `OLLAMA_CPU` - 2.0 CPU, 4GB RAM

**Example:**
```robot
*** Settings ***
Resource          resources/container_profiles.resource

Suite Setup       Create Container From Profile    PYTHON_STANDARD
Suite Teardown    Docker.Stop Container    ${CONTAINER_ID}

*** Test Cases ***
Test Code Generation
    ${code}=    LLM.Ask LLM    Write factorial function
    ${result}=    Docker.Execute Python In Container    ${code}
    Should Be Equal As Integers    ${result}[exit_code]    0
```

**Keywords:**
- `Docker.Create Configurable Container` - Create with resources
- `Docker.Execute In Container` - Run command
- `Docker.Execute Python In Container` - Run Python code
- `Docker.Stop Container` - Cleanup
- `Docker.Get Container Metrics` - Monitor usage
- `Docker.Find Available Port` - Find unused port (11434-11500)
- `Docker.Stop Container By Name` - Cleanup by container name

**Dynamic Port Allocation:**
LLM containers use dynamic port allocation to avoid conflicts:
```robot
${available_port}=    Docker.Find Available Port    11434    11500
${port_mapping}=    Create Dictionary    11434/tcp=${available_port}
${config}=    Create Dictionary    &{OLLAMA_CPU}    ports=${port_mapping}
${container}=    Docker.Create Configurable Container    ${config}
```

**Container Naming:**
Use unique names to prevent conflicts:
```robot
${timestamp}=    Evaluate    int(__import__('time').time())
${container_name}=    Set Variable    rfc-ollama-${timestamp}
```

---

## Testing Patterns

1. **Use `Ask LLM`** for prompting
2. **Use `Grade Answer`** for evaluation
3. **Assert on score** (0 or 1)
4. **Tag with IQ level** (IQ:100-160)
5. **Log outputs** for debugging

**Dependencies:**
- Docker daemon (required for container tests)
- Ollama (optional, default: http://localhost:11434)
- Python 3.11+
