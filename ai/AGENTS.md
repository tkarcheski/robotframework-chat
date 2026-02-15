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
4. Run `pre-commit run --all-files`
5. Commit: `<type>: <summary>`

**Prohibited:**
- Skip tests
- Commit failing code
- Bundle unrelated changes
- Mix formatting + logic
- Bypass pre-commit

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

**CI / GitHub Sync Warning:**
Running the GitLab CI pipeline resets the GitHub mirror. This means:
- Feature branches pushed to GitHub may be removed after a pipeline run
- Always push your branch **after** the pipeline completes if you need it on GitHub
- Do not assume a previously pushed branch still exists on GitHub — verify first
- Keep local branches until your PR is merged

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

# Lint & format
uv run ruff check .
uv run ruff check --fix .
uv run ruff format .
uv run mypy src/

# Pre-commit
pre-commit run --all-files
```

### Makefile Targets

```bash
make help          # Show all targets
make install       # Install dependencies (dev + superset)
make up            # Start PostgreSQL + Redis + Superset
make down          # Stop all services
make restart       # Restart all services
make logs          # Tail service logs
make bootstrap     # First-time Superset setup
make test          # Run all test suites (math, docker, safety)
make test-math     # Run math tests
make test-docker   # Run Docker tests
make test-safety   # Run safety tests
make import        # Import output.xml files: make import PATH=results/
make lint          # Run ruff linter
make format        # Auto-format code
make typecheck     # Run mypy type checker
make check         # Run all code quality checks
make version       # Print current version
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
│   ├─ CI Metadata (ci_metadata.py) ── GitLab CI env collection
│   ├─ CI Metadata Listener (ci_metadata_listener.py) ── attaches CI metadata to output
│   ├─ DB Listener (db_listener.py) ── archives results to SQL database
│   ├─ Ollama Timestamp Listener (ollama_timestamp_listener.py) ── timestamps Ollama chats
│   └─ Test Database (test_database.py) ── SQLite + PostgreSQL backends
│
├─> Listeners (auto-attached to every test run)
│   ├─ DbListener ── archives runs/results to SQL (SQLite or PostgreSQL)
│   ├─ CiMetadataListener ── adds CI context to Robot Framework output
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
│   └── roadmap.md              # Project roadmap
├── Makefile                    # Build, test, deploy targets
├── docker-compose.yml          # PostgreSQL + Redis + Superset stack
├── .env.example                # Environment variable template
├── pyproject.toml              # Python dependencies + optional extras
├── src/rfc/                    # Python keyword library
│   ├── __init__.py             # Package version (__version__)
│   ├── ollama.py               # Ollama API client
│   ├── models.py               # Shared data classes
│   ├── ci_metadata.py          # CI metadata collection
│   ├── ci_metadata_listener.py # Listener: CI metadata → Robot output
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
| `rfc.ci_metadata_listener.CiMetadataListener` | Collects GitLab CI metadata (commit, branch, pipeline URL, runner info) and adds it to test output |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamps every Ollama keyword call (Ask LLM, Wait For LLM, etc.) and saves `ollama_timestamps.json` |

All listeners are always active in the Makefile targets and in CI. Use them together:

```bash
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
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

The GitLab CI pipeline uses a seven-stage architecture:

```
sync → lint → generate → test → report → deploy → review
```

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

During the **test stage**, each suite runs with both listeners attached. The `DbListener` archives per-suite results to the database as each job completes.

During the **report stage**, `rebot` merges all `output.xml` files into a single combined report, and the combined results are imported into the database as a pipeline-level run.

During the **deploy stage** (default branch only), the Superset stack is deployed/updated on the target host.

During the **review stage** (MR label `claude-code-review` or manual trigger), Claude Code (Opus 4.6) inspects the pipeline for failed jobs, attempts to generate and apply fixes, then reviews the full MR diff against `ai/AGENTS.md` and `ai/REFACTOR.md`.

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
