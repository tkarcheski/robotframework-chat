---
name: converting-tests
description: >-
  Migrates tests from other frameworks (pytest-only, unittest, shell scripts,
  ad-hoc scripts) into the robotframework-chat tiered test system. Covers the
  tier decision tree, mapping assertions to Robot Framework keywords, extracting
  Python logic into keyword libraries, parameterized tests, fixtures, tagging,
  and suite registration.
when_to_use: >-
  Trigger when the user wants to convert, migrate, or port an existing test into
  the rfc framework, asks "which tier should this test be?", or is moving a
  pytest/unittest/shell test into robot/.
---

# Converting tests to the RFC framework

## When to Use

Use this skill when migrating tests from other frameworks (pytest-only, unittest,
shell scripts, ad-hoc scripts) into the robotframework-chat tiered test system.

## Decision Tree: Which Tier?

```
Does the test need an LLM to generate a response?
├── NO
│   ├── Can it be verified with RF built-in keywords only?
│   │   ├── YES → Tier 0 (verify:robot) — see the creating-tier0-tests skill
│   │   └── NO  → Tier 1 (verify:python) — see the creating-tier1-tests skill
│   └── Does it need Docker execution?
│       └── YES → Tier 1 with Docker keywords
├── YES
│   ├── Is a single LLM grader sufficient?
│   │   └── YES → Tier 2 (verify:llm)
│   ├── Do you need 3+ graders with majority vote?
│   │   └── YES → Tier 3 (verify:llms)
│   └── Does LLM output need Docker sandboxing?
│       └── YES → Tier 4
└── Just collecting data, no pass/fail?
    └── YES → Tier 6
```

## Step-by-Step Migration

### 1. Analyze the Source Test

Before converting, answer these questions:

- **What is being asserted?** (`assert x == y`, `assertRaises`, exit codes, etc.)
- **What dependencies does it have?** (network, files, databases, Docker, LLMs)
- **Is it deterministic?** Same input always produces same output?
- **What's the test data?** Hardcoded, parameterized, or external?

### 2. Map Assertions to RF Keywords

| Source Pattern | RF Equivalent | Tier |
|----------------|---------------|------|
| `assert x == y` | `Should Be Equal` | 0 |
| `assert x in y` | `Should Contain` | 0 |
| `assert x > 0` | `Should Be True    ${x} > 0` | 0 |
| `re.match(pattern, x)` | `Should Match Regexp` | 0 |
| `assert len(x) == 5` | `Length Should Be    ${x}    5` | 0 |
| `assertRaises(ValueError)` | `Run Keyword And Expect Error` | 0 |
| `json.loads(x)["key"]` | Python keyword → RF assert | 1 |
| `subprocess.run(cmd)` | Docker keyword → RF assert | 1 |
| `response = llm.generate(...)` | `LLM.Ask LLM` → `LLM.Grade Answer` | 2+ |

### 3. Extract Python Logic (Tier 1+)

If the source test has complex logic, extract it into a keyword library:

**Before (pytest-only):**
```python
def test_parse_config():
    config = parse_config("input.yaml")
    assert config["key"] == "value"
    assert len(config["items"]) == 3
```

**After (RFC tier:1):**

`src/rfc/config_keywords.py`:
```python
"""Config parsing keywords for Robot Framework."""

import yaml


class ConfigKeywords:
    ROBOT_LIBRARY_SCOPE = "SUITE"

    def parse_config_file(self, path: str) -> dict[str, object]:
        """Parse a YAML config file and return its contents."""
        with open(path) as f:
            return yaml.safe_load(f)
```

`tests/test_config_keywords.py`:
```python
from rfc.config_keywords import ConfigKeywords

class TestConfigKeywords:
    def test_parse_config_file(self, tmp_path):
        config_file = tmp_path / "test.yaml"
        config_file.write_text("key: value\nitems: [1, 2, 3]")
        kw = ConfigKeywords()
        result = kw.parse_config_file(str(config_file))
        assert result["key"] == "value"
        assert len(result["items"]) == 3
```

`robot/<domain>/tests/test_config.robot`:
```robot
*** Settings ***
Library    rfc.config_keywords.ConfigKeywords    WITH NAME    Config

*** Test Cases ***
Config File Parses Correctly
    [Tags]    tier:1    verify:python
    ${config}=    Config.Parse Config File    ${CURDIR}/fixtures/test.yaml
    Should Be Equal    ${config}[key]    value
    Length Should Be    ${config}[items]    3
```

### 4. Handle Parameterized Tests

**pytest parametrize → Robot FOR loop:**

```python
# Before
@pytest.mark.parametrize("a,b,expected", [(1,2,3), (4,5,9)])
def test_add(a, b, expected):
    assert add(a, b) == expected
```

```robot
# After
*** Test Cases ***
Addition Is Correct
    [Tags]    tier:0    verify:robot
    [Template]    Verify Addition
    1    2    3
    4    5    9

*** Keywords ***
Verify Addition
    [Arguments]    ${a}    ${b}    ${expected}
    ${result}=    Evaluate    ${a} + ${b}
    Should Be Equal As Integers    ${result}    ${expected}
```

**pytest parametrize → Robot data-driven with YAML:**

```robot
*** Settings ***
Variables    ${CURDIR}/../variables/test_data.yaml

*** Test Cases ***
Data-Driven Test
    [Tags]    tier:0    verify:robot
    FOR    ${item}    IN    @{TEST_DATA}
        Should Be Equal    ${item}[input]    ${item}[expected]
    END
```

### 5. Handle Test Fixtures

| pytest Fixture | RF Equivalent |
|----------------|---------------|
| `@pytest.fixture` (function) | `[Setup]` / `[Teardown]` per test |
| `@pytest.fixture(scope="module")` | `Suite Setup` / `Suite Teardown` |
| `tmp_path` | `${TEMPDIR}` or `Create Directory` |
| `monkeypatch.setenv` | `Set Environment Variable` |
| Mock objects | Keep in Python tests; Robot tests use real (or Docker) integration |

### 6. Apply Tags and Register

1. Add `tier:*` and `verify:*` tags to every test case
2. Register the suite in `config/test_suites.yaml`
3. Register the suite in `config/local_models.yaml`

### 7. Verify

```bash
# Original Python tests still pass (don't delete them yet)
uv run pytest tests/test_<original>.py -v

# New Python keyword tests pass
uv run pytest tests/test_<keywords>.py -v

# Robot dry run passes
make robot-dryrun

# Pre-commit passes
pre-commit run --all-files
```

## Architecture Rules

- **Don't duplicate logic.** The Python test (`tests/test_*.py`) validates the
  keyword library. The Robot test validates the system integration. They test
  different things.
- **Python logic goes in `src/rfc/`.** Never put business logic in `tests/` or
  `robot/`.
- **Keep the original tests** until you're confident the RFC versions cover
  the same ground. Then delete the originals in a separate commit.

## Common Pitfalls

1. **1:1 translation trap** — don't blindly convert every pytest to a Robot test.
   Some tests belong as pytest-only (unit tests of internal helpers). Only convert
   tests that validate *system behavior*.
2. **Over-tiering** — if you can do it with `Should Be Equal`, it's tier:0.
   Don't reach for Python or LLM grading unnecessarily.
3. **Mixing concerns** — one commit for extracting Python keywords, a separate
   commit for the Robot test, a separate commit for config registration.
4. **Forgetting the pytest** — every new Python keyword library needs a
   corresponding `tests/test_*.py`. TDD is mandatory.
