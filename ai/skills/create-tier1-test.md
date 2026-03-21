# Skill: Create a Tier:1 Robot + Python Test

## When to Use

Use this skill when creating a test that requires **Python-backed logic** for
verification — parsing, computation, data transformation, API calls (non-LLM),
or any logic too complex for pure RF built-in keywords.

The Python code lives in `src/rfc/`, the Robot test calls it via keyword libraries,
and a pytest in `tests/` validates the Python logic independently.

**Good candidates for tier:1:**
- Tests that need Python parsing (JSON, XML, regex beyond RF's built-in)
- Docker container execution with exit code checks
- Database queries and validation
- File format conversion and validation
- Complex math or algorithmic checks
- Safety/security checks with structured Python logic

## Required Tags

```robot
[Tags]    tier:1    verify:python
```

Or at suite level in `__init__.robot`:

```robot
Force Tags    tier:1    verify:python
```

## Step-by-Step

### 1. Write the Failing Python Test First (TDD)

Create `tests/test_<module>.py`:

```python
"""Tests for rfc.<module>.<ClassName>."""

from unittest.mock import MagicMock

import pytest

from rfc.<module> import <ClassName>


class Test<ClassName>:
    def test_basic_operation(self) -> None:
        # Arrange
        instance = <ClassName>()

        # Act
        result = instance.do_something("input")

        # Assert
        assert result == "expected"

    def test_edge_case(self) -> None:
        instance = <ClassName>()
        with pytest.raises(ValueError, match="descriptive message"):
            instance.do_something("")
```

Run it — it should fail:

```bash
uv run pytest tests/test_<module>.py -v
```

### 2. Implement the Python Keyword Library

Create `src/rfc/<module>.py`:

```python
"""<Module description> — Robot Framework keyword library."""


class <ClassName>:
    """RF keyword library for <domain> operations."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def do_something(self, input_value: str) -> str:
        """<Keyword documentation for RF logs>.

        Args:
            input_value: Description of the parameter.

        Returns:
            Description of return value.

        Raises:
            ValueError: If input_value is empty.
        """
        if not input_value:
            raise ValueError("descriptive message")
        return f"processed: {input_value}"
```

**Python rules:**
- Type hints on all parameters and return values
- `mypy` must pass
- No `Optional` for dataclass database fields — use concrete defaults
- `ROBOT_LIBRARY_SCOPE` set appropriately (`SUITE`, `TEST`, or `GLOBAL`)

Run the test again — it should pass:

```bash
uv run pytest tests/test_<module>.py -v
```

### 3. Create the Robot Test

Create `robot/<domain>/tests/test_<name>.robot`:

```robot
*** Settings ***
Documentation     <Suite description>
Library           rfc.<module>.<ClassName>    WITH NAME    <Alias>

*** Test Cases ***
Descriptive Test Name
    [Documentation]    <What this verifies>
    [Tags]    tier:1    verify:python
    ${result}=    <Alias>.Do Something    input_value
    Should Be Equal    ${result}    processed: input_value

Edge Case Handling
    [Documentation]    Verify error handling for invalid input
    [Tags]    tier:1    verify:python
    Run Keyword And Expect Error    ValueError: descriptive message
    ...    <Alias>.Do Something    ${EMPTY}
```

### 4. Create Shared Resources (Optional)

If multiple test files share keywords, create `robot/<domain>/<domain>.resource`:

```robot
*** Settings ***
Documentation     Shared keywords for <domain> tests
Library           rfc.<module>.<ClassName>    WITH NAME    <Alias>

*** Keywords ***
Setup <Domain> Environment
    [Documentation]    Common setup for <domain> tests
    Log    Setting up <domain> environment

Validate <Domain> Result
    [Arguments]    ${result}    ${expected}
    Should Be Equal    ${result}    ${expected}
```

### 5. Register the Suite

Add to **both** config files (see `create-tier0-test.md` § Register the Suite
for the exact YAML format).

### 6. Verify Everything

```bash
# Python tests pass
uv run pytest tests/test_<module>.py -v

# Type checking passes
uv run mypy src/rfc/<module>.py

# Robot syntax valid
make robot-dryrun

# All pre-commit checks pass
pre-commit run --all-files
```

## Reference Examples

### Python Keyword Libraries

| File | Pattern |
|------|---------|
| `src/rfc/docker_keywords.py` | Docker execution keywords with `ROBOT_LIBRARY_SCOPE` |
| `src/rfc/superset_keywords.py` | Database query keywords |
| `src/rfc/safety_keywords.py` | Safety evaluation with structured Python logic |
| `src/rfc/grader.py` | Grading logic with `GradeResult` dataclass |

### Corresponding Python Tests

| File | Pattern |
|------|---------|
| `tests/test_docker_keywords.py` | Mock-based Docker tests |
| `tests/test_grader.py` | Grader with mock LLM client |
| `tests/conftest.py` | Shared fixtures: `mock_ollama_client`, `tmp_db`, `sample_test_run` |

### Robot Tests Using Python Keywords

| File | Pattern |
|------|---------|
| `robot/docker/shell/tests/terminal_workflow.robot:55` | Docker exec + RF assert |
| `robot/safety/__init__.robot:37` | Suite-level `Force Tags tier:1 verify:python` |
| `robot/docker/python/tests/code_generation.robot:113` | Resource limit checks |

## Common Pitfalls

1. **Skipping TDD** — always write the failing pytest *first*. The Python test
   tests the keyword logic; the Robot test tests the integration.
2. **Putting logic in Robot** — if you need an `IF`/`ELSE` chain or string
   parsing in Robot, it probably belongs in Python instead.
3. **Missing type hints** — `mypy` is enforced via pre-commit. Add hints to
   every function signature.
4. **Importing LLM keywords** — if your Python code calls `OllamaClient.generate()`
   or similar, it's tier:2, not tier:1.
5. **Wrong scope** — `ROBOT_LIBRARY_SCOPE = "SUITE"` is correct for most cases.
   Use `"TEST"` only if each test needs a fresh instance.
6. **Not mocking externals** — Python tests should mock I/O (Docker, network, DB).
   Use `unittest.mock.MagicMock` or the fixtures in `tests/conftest.py`.
