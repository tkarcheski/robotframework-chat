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
make test                   # Run all test suites (math, docker, safety)
make test-math              # Run math tests
make test-docker            # Run Docker tests
make test-safety            # Run safety tests
```

### Superset Dashboard

```bash
cp .env.example .env        # Configure environment
make up                     # Start PostgreSQL + Redis + Superset
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

- **LLMs are software** — they should be tested like software
- **Judging must be constrained** — graders return structured data only
- **Determinism first, intelligence later**
- **Robot Framework as the orchestration layer**
- **CI-native, regression-focused**
- **Every test run is archived** — listeners always active

---

## Documentation

| Document | Description |
|----------|-------------|
| [ai/AGENTS.md](ai/AGENTS.md) | Agent instructions, architecture, and detailed reference |
| [ai/DEV.md](ai/DEV.md) | Development guidelines and TDD workflow |
| [ai/SKILLS.md](ai/SKILLS.md) | Agent capabilities and tools |
| [ai/roadmap.md](ai/roadmap.md) | Project roadmap |
| [docs/TEST_DATABASE.md](docs/TEST_DATABASE.md) | Database schema and usage |
| [docs/GITLAB_CI_SETUP.md](docs/GITLAB_CI_SETUP.md) | CI/CD setup guide |

---

## Contributing

1. Follow the code style guidelines in [ai/AGENTS.md](ai/AGENTS.md)
2. Add tests for new features
3. Run `pre-commit run --all-files` before committing
4. See [ai/DEV.md](ai/DEV.md) for the full development workflow
