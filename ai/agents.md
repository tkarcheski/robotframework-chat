# ai/agents.md: the contribution contract

**Plain version:**

- This repo tests LLMs and coding agents the way you'd test any software:
  inputs, outputs, regressions, CI.
- **Robot Framework orchestrates. Python implements.** Never the other way round.
- **Every run is archived.** Listeners are always on; if it ran, it's in SQL.
- **Deterministic checks first.** Fuzzy LLM scoring only on top of that.
- Python lives in `src/rfc/`. Robot tests live in `robot/`. Nowhere else.

This is the contract for agents *and* humans. Tiers and test rules:
[testing.md](testing.md). Always-loaded workflow rules: repo-root `CLAUDE.md`.
Docs style: [writing.md](writing.md).

---

## Core philosophy

1. **LLMs are software: test them like software.** Same CI, versioning, and
   regression discipline as any code.
2. **Determinism before intelligence.** Machine-verifiable evaluation first;
   fuzzy scoring only on a solid deterministic foundation.
3. **Constrained grading.** Graders return structured data only: scores,
   categories, pass/fail. **No prose from the evaluation layer.**
4. **Modular by design.** New providers, graders, test types, and output formats
   plug in without rewriting core.
5. **Robot orchestrates, Python implements.** Robot handles lifecycle,
   sequencing, and reporting.
6. **Every test run is archived.** Listeners always active, results flow to SQL.
   If it ran, it's queryable.
7. **CI-native.** If it can't run unattended, it's not done.

---

## The contract

### Do

1. **Failing test first** (red) → minimal code (green) → refactor.
2. **Quality checks before committing:** `make code-quality-check` and
   `pre-commit run --all-files`.
3. **Commit format:** `<type>: <summary>`: `test:`, `feat:`, `fix:`,
   `refactor:`, `docs:`, `chore:`.
4. **Validate what the user hands you** before acting on it:
   - Check paths against the layout rules below
   - Verify referenced files/symbols actually exist
   - Read shell commands for dangerous operations before running them
   - Flag requests contradicting decisions recorded here or in `testing.md`

   Caught a mistake? **Say so and propose the correction.** Never silently
   "fix" it.

### Don't

- Skip tests, commit failing code, or bypass pre-commit / Makefile checks.
- Bundle unrelated changes, or mix formatting with logic.
- Commit `uv.lock` or any other generated lockfile (gitignored).

### Layout

- `src/rfc/`: single source of truth for all Python.
- `robot/`: single home for all Robot test suites.
- **Never duplicate logic outside these two directories.**

### Branching

Feature branches off `claude-code-staging`, the integration branch, **not**
`main`. Rebase onto it before pushing.

---

## Commands

`make help` lists everything. These are the ones you'll actually use:

```bash
make install               # uv sync (dev + superset extras)
uv run pytest              # Python unit tests
make code-quality-check    # lint (ruff) + typecheck (mypy) + coverage
pre-commit run --all-files # final gate: yaml, json, whitespace, ruff, mypy
make robot-dryrun          # validate all Robot suites parse
make robot                 # all Robot suites (also robot-math, robot-docker, robot-safety)
make docker-up             # PostgreSQL + Redis + Superset stack
make import RESULTS_DIR=results/   # import output.xml into the DB

# One test:
uv run robot -d results -t "Test Name" robot/path/tests/file.robot
```

**Debugging order: foundation up.** Fix Robot test failures before looking at
Docker or CI. Fix code-quality failures before pipelines.

---

## Code style

### Python

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

# Error handling: always chain the cause
except json.JSONDecodeError as e:
    raise ValueError(f"Invalid JSON: {raw}") from e
```

### Robot Framework

```robot
*** Settings ***
Documentation     Clear description
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Test Cases ***
Test Case Name
    [Documentation]    What this tests
    [Tags]    tier:2    verify:llm
    ${answer}=    LLM.Ask LLM    ${QUESTION}
    Should Be Equal    ${answer}    ${EXPECTED}

*** Keywords ***
Custom Keyword
    [Arguments]    ${arg}
    [Documentation]    What this keyword does
    RETURN    ${result}    # Use RETURN, not [Return]
```

- `RETURN`, never the deprecated `[Return]`.
- Every test: exactly one `tier:*` and one `verify:*`. Every suite: one `axis:*`
  (see `testing.md`).
- `Suite Setup` / `Suite Teardown` for container lifecycle.
- Variables: `${scalar}`, `@{list}`, `&{dict}`.

---

## Architecture

```
Robot Framework Test
│
├─> Python Keyword Library (src/rfc/)
│   ├─ LLM clients (ollama.py, llm_client.py) ── generation + model discovery
│   ├─ Graders (grader.py, safety_grader.py)
│   ├─ Docker Manager (container_manager.py)
│   ├─ Keywords (keywords.py, docker_keywords.py, safety_keywords.py)
│   └─ Data Models (models.py) ── GradeResult, SafetyResult
│
├─> Listeners (auto-attached to every test run)
│   ├─ DbListener ── archives runs/results to SQL (SQLite or PostgreSQL)
│   ├─ GitMetaData ── adds CI context (commit, branch, run URL) to output
│   └─ OllamaTimestampListener ── timestamps every Ollama chat call
│
├─> Docker Containers ── sandboxed code execution + LLM services
│
├─> Superset Stack (docker-compose.yml) ── PostgreSQL 16, Redis 7, Superset
│
└─> Results ── Robot HTML reports, SQL history, Superset dashboards
```

**CI:** GitHub Actions in `.github/workflows/`: `robot-tests.yml` (lint,
pytest, Robot dry-run, robot tests), `docker-publish.yml` (Docker image),
`pypi-publish.yml` (PyPI on `v*` tags).

**All executable logic stays in Makefile targets** so it runs identically in CI
and locally. To change what a job does, edit the Makefile (or the scripts it
wraps), **not** the workflow YAML.

---

## Listeners & database

All three attach automatically via the Makefile targets and CI:

| Listener | Purpose |
|----------|---------|
| `rfc.db_listener.DbListener` | Archives test runs and results to SQL |
| `rfc.git_metadata_listener.GitMetaData` | Adds CI metadata to Robot output |
| `rfc.ollama_timestamp_listener.OllamaTimestampListener` | Timestamps Ollama keyword calls; saves `ollama_timestamps.json` |

Results land in PostgreSQL. **`DATABASE_URL` must be set** in the environment or
`.env` (e.g. `postgresql://rfc:changeme@localhost:5433/rfc`). SQLite is used
only by test fixtures.

Schema, queries, maintenance: [../docs/TEST_DATABASE.md](../docs/TEST_DATABASE.md)
(path relative to the published `ai/` location). Environment variables:
`.env.example`.

---

## Docker testing

Container profiles live in `robot/resources/container_profiles.resource`:
MINIMAL / STANDARD / PERFORMANCE / NETWORKED / OLLAMA_CPU.

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

**Key keywords:** `Docker.Create Configurable Container`, `Docker.Execute In
Container`, `Docker.Execute Python In Container`, `Docker.Stop Container`,
`Docker.Get Container Metrics`.

**Two that save you pain:**

- `Docker.Find Available Port`: use it instead of hardcoding. LLM containers
  allocate from 11434-11500.
- `Docker.Stop Container By Name`: use unique, timestamped container names.

**Dependencies:** Docker daemon (container tests), Ollama endpoint (LLM tests,
default `http://localhost:11434`), Python 3.11+.

---

## Agent workflow capture

For tests exercising multi-turn agent behaviour: messages, tool calls, state
evolution:

| Piece | Module | Does |
|---|---|---|
| Library | `rfc.agent_workflow_keywords.AgentWorkflowKeywords` | The Robot surface |
| Tracker | `rfc.agent_interaction_tracker.AgentInteractionTracker` | Builds an immutable `AgentWorkflow`: frozen interactions, tool calls, results |
| Validator | `rfc.tool_call_validator.ToolCallValidator` | Enforces schema, ordering, result expectations |
| Memory | `rfc.agent_memory_manager.MemoryManager` | Sliding-window short-term, vector long-term, schema-checked persistent |
| Listener | `rfc.agent_workflow_listener.AgentWorkflowListener` | Persists the `agent_workflow` RFC_DATA payload at end-of-test |

Example tests: `robot/30__tier3/agent_workflows/tests/`.
Suite guide: `robot/30__tier3/agent_workflows/README.md`.
