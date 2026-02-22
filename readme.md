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
make install                # Install all dependencies
pre-commit install          # Install pre-commit hooks
ollama pull llama3          # Pull default LLM model (optional)
```

### Running Tests

```bash
make robot                  # Run all Robot Framework test suites
make robot-math             # Run math tests
make robot-docker           # Run Docker tests
make robot-safety           # Run safety tests
```

### Superset Dashboard

```bash
cp .env.example .env        # Configure environment
make docker-up              # Start PostgreSQL + Redis + Superset
make bootstrap              # First-time Superset initialization
open http://localhost:8088   # Open the dashboard
```

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
| [ai/CLAUDE.md](ai/CLAUDE.md) | Project intelligence, owner decisions, architecture vision |
| [ai/AGENTS.md](ai/AGENTS.md) | Agent instructions, code style, and commands |
| [ai/DEV.md](ai/DEV.md) | Development guidelines and TDD workflow |
| [ai/FEATURES.md](ai/FEATURES.md) | Feature tracker (prioritized, with status) |
| [ai/PIPELINES.md](ai/PIPELINES.md) | Pipeline strategy and model selection |
| [ai/DEVOPS.md](ai/DEVOPS.md) | DevOps practices tracker |
| [ai/REFACTOR.md](ai/REFACTOR.md) | Refactoring and maintenance guide |
| [docs/TEST_DATABASE.md](docs/TEST_DATABASE.md) | Database schema and usage |
| [docs/GITLAB_CI_SETUP.md](docs/GITLAB_CI_SETUP.md) | CI/CD setup guide |
| [humans/TODO.md](humans/TODO.md) | Owner action items and decisions |
| [humans/QA_TRANSCRIPT.md](humans/QA_TRANSCRIPT.md) | Full Q&A from spec review sessions |

---

## Contributing

1. Follow the code style guidelines in [ai/AGENTS.md](ai/AGENTS.md)
2. Add tests for new features
3. Run `pre-commit run --all-files` before committing
4. See [ai/DEV.md](ai/DEV.md) for the full development workflow
