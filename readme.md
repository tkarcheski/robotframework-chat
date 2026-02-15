# robotframework-chat

A Robot Framework-based test harness for systematically testing Large Language Models (LLMs) using LLMs as both the system under test and as automated graders. Test results are archived to SQL and visualized in Apache Superset dashboards.

---

## Quick Start

### Prerequisites

- **Python 3.11+** and **astral-uv** for dependency management
- **Docker** for containerized code execution, LLM testing, and the Superset stack
- **Ollama** (optional) for local LLM testing

### Installation

```bash
# Install all dependencies (including Superset/PostgreSQL support)
make install
# or: uv sync --extra dev --extra superset

# Install pre-commit hooks
pre-commit install

# Pull default LLM model (optional)
ollama pull llama3
```

### Running Tests

Every test run automatically archives results to the database via listeners.

```bash
# Run all test suites (math, docker, safety)
make test

# Run individual suites
make test-math
make test-docker
make test-safety

# Run with custom options
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/math/tests/

# Run specific test by name
uv run robot -d results -t "LLM Can Do Basic Math" \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/math/tests/llm_maths.robot

# Run tests by IQ tag
uv run robot -d results -i IQ:120 \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/docker/python
```

### Superset Dashboard Setup

```bash
# 1. Configure environment
cp .env.example .env       # edit credentials

# 2. Start the stack (PostgreSQL + Redis + Superset)
make up

# 3. First-time Superset initialization
make bootstrap

# 4. Open the dashboard
open http://localhost:8088  # login with credentials from .env
```

---

## Listeners

Two Robot Framework listeners handle test result collection:

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives test runs and individual results to the SQL database (SQLite or PostgreSQL) |
| `rfc.ci_metadata_listener.CiMetadataListener` | Collects GitLab CI metadata (commit, branch, pipeline URL, runner info) and adds it to test output |

Both listeners are always active in the Makefile targets and in CI. Use them together:

```bash
uv run robot -d results/math \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/math/tests/
```

The `DbListener` reads `DATABASE_URL` from the environment to decide where to store results:

| `DATABASE_URL` | Backend | Notes |
|----------------|---------|-------|
| Not set | SQLite | Stores to `data/test_history.db` |
| `postgresql://...` | PostgreSQL | Requires `uv sync --extra superset` |

---

## CI/CD Pipeline

The GitLab CI pipeline uses a five-stage architecture:

```
sync → lint → test → report → deploy
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
│   └─ Test Database (test_database.py) ── SQLite + PostgreSQL backends
│
├─> Listeners (auto-attached to every test run)
│   ├─ DbListener ── archives runs/results to SQL (SQLite or PostgreSQL)
│   └─ CiMetadataListener ── adds CI context to Robot Framework output
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

See [docs/TEST_DATABASE.md](docs/TEST_DATABASE.md) for schema details, queries, and maintenance.

---

## Makefile Targets

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

## Overview

`robotframework-chat` is an **infrastructure-first** testing platform designed for:

- **Deterministic LLM evaluation** - Machine-verifiable test results
- **Containerized code execution** - Safe, isolated testing environments
- **Multi-model comparison** - Test multiple LLMs simultaneously
- **CI/CD integration** - Automated regression detection with database archiving
- **Superset dashboards** - Visual trend analysis and model comparison
- **Scalable test organization** - IQ-tagged difficulty levels

### Core Philosophy

- **LLMs are software** → they should be tested like software
- **Judging must be constrained** → graders return structured data only
- **Determinism first, intelligence later**
- **Robot Framework as the orchestration layer**
- **CI-native, regression-focused**
- **Every test run is archived** → listeners always active

---

## Example Tests

### Basic LLM Test

```robot
*** Test Cases ***
LLM Can Do Basic Math
    ${answer}=    Ask LLM    What is 2 + 2?
    ${score}    ${reason}=    Grade Answer    What is 2 + 2?    4    ${answer}
    Should Be Equal As Integers    ${score}    1
```

### Docker Code Execution

```robot
*** Settings ***
Resource          resources/container_profiles.resource

Suite Setup       Create Container From Profile    PYTHON_STANDARD
Suite Teardown    Docker.Stop Container    ${CONTAINER_ID}

*** Test Cases ***
LLM Generates Working Code (IQ:120)
    ${code}=    LLM.Ask LLM    Write a Python factorial function
    ${result}=    Docker.Execute Python In Container    ${code}
    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    120
```

---

## Repository Structure

```
robotframework-chat/
├── readme.md                   # This file
├── ROADMAP.md                  # Project roadmap
├── AGENTS.md                   # Agent instructions
├── DEV.md                      # Development guidelines
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
├── superset/                   # Superset configuration
│   ├── superset_config.py      # Superset settings
│   └── bootstrap_dashboards.py # Pre-configured charts & dashboard
├── scripts/                    # Import/query/CI utilities
│   ├── import_test_results.py  # Import output.xml → database
│   └── generate_ci_metadata.py # Generate CI metadata JSON
├── docs/                       # Additional documentation
│   ├── TEST_DATABASE.md        # Database schema & usage
│   └── GITLAB_CI_SETUP.md      # CI/CD setup guide
├── data/                       # SQLite database (gitignored)
├── results/                    # Test output (gitignored)
└── .pre-commit-config.yaml     # Git hooks
```

---

## Development

### Code Quality

```bash
make lint          # ruff check .
make format        # ruff format .
make typecheck     # mypy src/
make check         # lint + typecheck

# Or run manually
pre-commit run --all-files
```

### Running Tests with Debug Output

```bash
uv run robot -d results -L DEBUG \
  --listener rfc.db_listener.DbListener \
  --listener rfc.ci_metadata_listener.CiMetadataListener \
  robot/math/tests/
```

---

## Contributing

1. Follow the code style guidelines in `AGENTS.md`
2. Add tests for new features
3. Update documentation
4. Run pre-commit hooks before committing

---

## Support

For issues and feature requests, please use the GitHub issue tracker.
