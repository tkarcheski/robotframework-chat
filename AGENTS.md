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
uv sync

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

## Project Structure

```
robotframework-chat/
├── src/rfc/                    # Python library (canonical source)
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
├── robot/                      # All Robot Framework test suites
│   ├── math/tests/             # Math tests
│   ├── docker/python/tests/    # Python execution
│   ├── docker/llm/tests/       # LLM-in-Docker
│   ├── docker/shell/tests/     # Shell tests
│   ├── safety/                 # Safety/security tests
│   │   ├── test_cases/         # .robot test files
│   │   ├── variables/          # YAML test data
│   │   └── safety.resource     # Shared keywords/config
│   ├── ci/                     # CI model metadata
│   └── resources/              # Reusable configs
│       ├── container_profiles.resource
│       ├── environments.resource
│       └── llm_containers.resource
├── dashboard/                  # Dash-based test runner UI
│   └── core/
│       ├── llm_registry.py     # Model discovery (wraps OllamaClient)
│       ├── robot_runner.py     # Threaded test runner
│       └── session_manager.py  # Multi-session management
├── scripts/                    # Utility scripts
├── pyproject.toml
├── AGENTS.md
└── DEV.md
```

**Important:** `src/rfc/` is the single source of truth for all Python code.
`robot/` is the single home for all Robot Framework test suites. Never duplicate
logic outside of these directories.

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
