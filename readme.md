# robotframework-chat

A Robot Framework-based test harness for systematically testing Large Language Models (LLMs) using LLMs as both the system under test and as automated graders.

---

## Quick Start

### Prerequisites

- **Docker** - Required for containerized code execution and LLM testing
- **Python 3.11+** - For running the test framework
- **astral-uv** - For dependency management
- **Ollama** (optional) - For local LLM testing

### Installation

```bash
# Clone and setup
uv sync

# Install pre-commit hooks
pre-commit install

# Pull default LLM model (optional)
ollama pull llama3
```

### Running Tests

```bash
# Run all math tests
uv run robot -d results robot/math

# Run Docker-based Python tests
uv run robot -d results robot/docker/python

# Run LLM-in-Docker multi-model tests
uv run robot -d results robot/docker/llm

# Run safety tests
uv run robot -d results robot/safety

# Run specific test by name
uv run robot -d results -t "LLM Can Do Basic Math" robot/math/tests/llm_maths.robot

# Run tests by IQ tag
uv run robot -d results -i IQ:120 robot/docker/python
```

---

## Overview

`robotframework-chat` is an **infrastructure-first** testing platform designed for:

- **Deterministic LLM evaluation** - Machine-verifiable test results
- **Containerized code execution** - Safe, isolated testing environments
- **Multi-model comparison** - Test multiple LLMs simultaneously
- **CI/CD integration** - Automated regression detection
- **Scalable test organization** - IQ-tagged difficulty levels

### Core Philosophy

- **LLMs are software** → they should be tested like software
- **Judging must be constrained** → graders return structured data only
- **Determinism first, intelligence later**
- **Robot Framework as the orchestration layer**
- **CI-native, regression-focused**

---

## Key Capabilities

### Current Features

✅ **LLM Testing**
- Prompt LLMs from Robot Framework
- Grade responses using LLM-based judges
- Binary (0/1) and rubric-based scoring
- JSON-only grading contracts
- Local (Ollama) and remote model support

✅ **Docker-Based Code Execution**
- Run Python, Node.js, and shell code in isolated containers
- Configurable CPU, memory, and network constraints
- Read-only filesystems for security
- No subprocess calls - pure Docker SDK

✅ **LLM-in-Docker**
- Run Ollama in containers with resource limits
- Multi-model comparison testing
- Suite-level container lifecycle management

✅ **Safety Testing**
- Prompt injection resistance testing
- System prompt extraction detection
- Jailbreak attempt validation
- Regex-based pattern detection with confidence scoring

✅ **Test Organization**
- IQ levels (100-160) for difficulty progression
- Tag-based filtering and execution
- Reusable resource files for environments
- Multi-session dashboard UI for concurrent test runs

✅ **CI/CD Integration**
- GitLab CI pipeline with pre-run model filtering
- Automatic CI metadata collection
- SQLite database for test history tracking
- Import/export utilities for test results

### Planned Features

See [ROADMAP.md](ROADMAP.md) for detailed planning.

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
│   └─ Test Database (test_database.py) ── SQLite results storage
│
├─> Docker Containers
│   ├─ Code Execution (Python, Node, Shell)
│   └─ LLM Services (Ollama)
│
├─> Dashboard (dashboard/)
│   └─ Multi-session test runner UI (Dash)
│
└─> Test Results & Reports
```

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

### Multi-Model Comparison

```robot
*** Settings ***
Resource          resources/llm_containers.resource

Suite Setup       Start LLM Container    OLLAMA_CPU    pull_models=llama3,codellama
Suite Teardown    Stop LLM Container

*** Test Cases ***
Compare Models (IQ:130)
    ${responses}=    Ask Multiple LLMs    Write a sort function    llama3,codellama
    ${comparison}=    Run Multi-Model Comparison    Write a sort function
    Log    Best model: ${comparison}[best_model]
```

---

## Docker Configuration

### Container Profiles

Pre-defined resource profiles in `robot/resources/container_profiles.resource`:

| Profile | CPU | Memory | Network | Use Case |
|---------|-----|--------|---------|----------|
| `MINIMAL` | 0.25 cores | 128 MB | None | Simple scripts |
| `STANDARD` | 0.5 cores | 512 MB | None | General testing |
| `PERFORMANCE` | 1.0 cores | 1 GB | None | Heavy computation |
| `NETWORKED` | 0.5 cores | 512 MB | Bridge | Network access needed |
| `OLLAMA_CPU` | 2.0 cores | 4 GB | Bridge | LLM inference |

### Custom Container Configuration

```robot
*** Variables ***
${custom_config}=    Create Dictionary
...    image=python:3.11-slim
...    cpu_cores=0.25
...    memory_mb=256
...    network_mode=none
...    read_only=True

*** Test Cases ***
Custom Resources (IQ:120)
    ${container}=    Docker.Create Configurable Container    ${custom_config}
    ${result}=    Docker.Execute In Container    ${container}    python3 -c "print('Hello')"
    Docker.Stop Container    ${container}
```

---

## Repository Structure

```
robotframework-chat/
├── README.md                   # This file
├── ROADMAP.md                  # Project roadmap
├── AGENTS.md                   # Agent instructions
├── DEV.md                      # Development guidelines
├── pyproject.toml              # Python dependencies
├── src/rfc/                    # Python keyword library (canonical source)
│   ├── ollama.py               # Ollama API client (generation + model discovery)
│   ├── models.py               # Shared data classes (GradeResult, SafetyResult)
│   ├── ci_metadata.py          # Shared CI metadata collection
│   ├── keywords.py             # Core LLM keywords
│   ├── grader.py               # LLM answer grading
│   ├── safety_keywords.py      # Safety testing keywords
│   ├── safety_grader.py        # Regex-based safety grading
│   ├── docker_config.py        # Container configuration models
│   ├── container_manager.py    # Docker lifecycle management
│   ├── docker_keywords.py      # Docker container keywords
│   ├── test_database.py        # SQLite test results database
│   ├── pre_run_modifier.py     # Dynamic model configuration
│   └── ci_metadata_listener.py # GitLab CI metadata listener
├── robot/                      # Robot Framework tests
│   ├── math/tests/             # Math reasoning tests
│   ├── docker/                 # Docker-based tests
│   │   ├── python/tests/       # Python code execution
│   │   ├── llm/tests/          # LLM-in-Docker tests
│   │   └── shell/tests/        # Shell/terminal tests
│   ├── safety/                 # Safety/security tests
│   └── resources/              # Reusable resource files
│       ├── container_profiles.resource
│       ├── environments.resource
│       └── llm_containers.resource
├── dashboard/                  # Dash-based test runner UI
│   └── core/                   # Session management, runner, model discovery
├── scripts/                    # Import/query/CI utilities
├── docs/                       # Additional documentation
├── results/                    # Test output (gitignored)
└── .pre-commit-config.yaml     # Git hooks
```

---

## Development

### Code Quality

```bash
# Run linting
uv run ruff check .

# Run formatting
uv run ruff format .

# Run type checking
uv run mypy src/

# Run pre-commit hooks
pre-commit run --all-files
```

### Running Tests

```bash
# Run specific test file
uv run robot -d results robot/docker/python/tests/code_generation.robot

# Run with specific tag
uv run robot -d results -i IQ:130 robot/docker/python

# Run with timeout
uv run robot -d results --variable DEFAULT_TIMEOUT:60 robot/docker/llm

# Dry run
uv run robot -d results --dryrun robot/docker/python
```

---

## Why Robot Framework?

- **Proven** in hardware, embedded, and systems testing
- **Clear separation** of intent (test cases) and implementation (keywords)
- **Excellent logs** and reports with built-in screenshots/logs
- **CI-native** with JUnit XML and other output formats
- **Familiar** to QA and systems engineers
- **Extensible** via Python libraries

---

## Contributing

1. Follow the code style guidelines in `AGENTS.md`
2. Add tests for new features
3. Update documentation
4. Run pre-commit hooks before committing

---


## Support

For issues and feature requests, please use the GitHub issue tracker.
