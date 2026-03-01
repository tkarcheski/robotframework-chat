# robotframework-chat

A Robot Framework-based test harness for systematically testing Large Language Models (LLMs) using LLMs as both the system under test and as automated graders. Test results are archived to SQL and visualized in Apache Superset dashboards.

---

## Quick Start

### Prerequisites

- **Python 3.11+** and **astral-uv** for dependency management
- **Docker** for containerized code execution, LLM testing, and the Superset stack
- **Ollama** (optional) for local LLM testing

### Installation (Linux / macOS)

```bash
make install                # Install all dependencies
pre-commit install          # Install pre-commit hooks
ollama pull llama3          # Pull default LLM model (optional)
```

### Installation (Windows)

The `tasks.py` script provides a cross-platform alternative to the Makefile.
It requires only Python and `uv` — no `make`, `bash`, or Unix tools needed.

```powershell
uv run python tasks.py install      # Install all dependencies
uv run pre-commit install           # Install pre-commit hooks
ollama pull llama3                  # Pull default LLM model (optional)
uv run python tasks.py help         # List all available targets
```

> **Note:** Docker-based tests require [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) with the WSL 2 backend enabled.

### Running Tests

```bash
# Linux / macOS
make robot                  # Run all Robot Framework test suites
make robot-math             # Run math tests
make robot-docker           # Run Docker tests
make robot-safety           # Run safety tests

# All platforms (including Windows)
uv run python tasks.py robot        # Run all suites
uv run python tasks.py robot-math   # Run math tests
uv run python tasks.py robot-dryrun # Validate tests (dry run)
uv run python tasks.py check        # Lint + typecheck + coverage
```

### Superset Dashboard

```bash
# Linux / macOS
cp .env.example .env        # Configure environment
make docker-up              # Start PostgreSQL + Redis + Superset
make bootstrap              # First-time Superset initialization

# Windows — tasks.py copies .env automatically if missing
uv run python tasks.py docker-up
```

Open <http://localhost:8088> to view the dashboard.

---

## Example Test

```robot
*** Test Cases ***
LLM Can Do Basic Math
    ${answer}=    Ask LLM    What is 2 + 2?
    ${score}    ${reason}=    Grade Answer    What is 2 + 2?    4    ${answer}
    Should Be Equal As Integers    ${score}    1
```

---

## Core Philosophy

- **LLMs are software** — test them like software
- **Determinism before intelligence** — structured, machine-verifiable evaluation first
- **Constrained grading** — scores, categories, pass/fail; no prose from the evaluation layer
- **Modular by design** — composable pieces; new providers and graders plug in without rewriting core
- **Robot Framework as the orchestration layer** — readable, keyword-driven tests
- **Every test run is archived** — listeners always active, results flow to SQL
- **CI-native, regression-focused** — if it can't run unattended, it's not done

See [ai/AGENTS.md](ai/AGENTS.md#core-philosophy) for the full philosophy.

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/TEST_DATABASE.md](docs/TEST_DATABASE.md) | Database schema and usage |
| [docs/GITLAB_CI_SETUP.md](docs/GITLAB_CI_SETUP.md) | CI/CD setup guide |
| [docs/GRAFANA_SUPERSET_SETUP.md](docs/GRAFANA_SUPERSET_SETUP.md) | Grafana & Superset visualization stack setup |
| [docs/SUPERSET_EXPORT_GUIDE.md](docs/SUPERSET_EXPORT_GUIDE.md) | Superset dashboard export, import, and backup |

---

## Contributing

1. Read [ai/DEV.md](ai/DEV.md) for the development workflow and TDD discipline
2. Follow the code style guidelines in [ai/AGENTS.md](ai/AGENTS.md)
3. Add tests for new features (see [ai/CLAUDE.md](ai/CLAUDE.md) for grading tiers)
4. Run `pre-commit run --all-files` before committing
