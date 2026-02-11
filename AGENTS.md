# Agent Instructions for robotframework-chat

A Robot Framework-based test harness for systematically testing LLMs.

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

---

## Commands

```bash
# Install
uv sync

# Run tests
uv run pytest
uv run robot -d results robot/math
uv run robot -d results robot/docker/python

# Run specific test
uv run robot -d results -t "Test Name" robot/path/tests/file.robot

# Run by tag
uv run robot -d results -i IQ:120 robot/docker/python

# Lint & format
uv run ruff check .
uv run ruff check --fix .
uv run ruff format .
uv run mypy src/

# Pre-commit
pre-commit install
pre-commit run --all-files
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
```

---

## Project Structure

```
robotframework-chat/
├── src/rfc/                    # Python library
│   ├── keywords.py             # Core LLM keywords
│   ├── docker_keywords.py      # Docker container keywords
│   ├── container_manager.py    # Container management
│   ├── docker_config.py        # Configuration models
│   ├── llm_client.py           # LLM API client
│   ├── grader.py               # Grading logic
│   └── models.py               # Data classes
├── robot/                      # Tests
│   ├── math/tests/             # Math tests
│   ├── docker/python/tests/    # Python execution
│   ├── docker/llm/tests/       # LLM-in-Docker
│   ├── docker/shell/tests/     # Shell tests
│   └── resources/              # Reusable configs
│       ├── container_profiles.resource
│       ├── environments.resource
│       └── llm_containers.resource
├── pyproject.toml
├── AGENTS.md
└── DEV.md
```

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
