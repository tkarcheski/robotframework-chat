---
name: creating-tier0-tests
description: >-
  Creates a pure Robot Framework (tier:0, verify:robot) test that verifies
  behaviour using only deterministic RF built-in assertions — no LLM calls and
  no Python-backed keywords. Covers good tier:0 candidates, required tags, the
  allowed built-in keywords, shared resources, and registering the suite in
  config/test_suites.yaml and config/local_models.yaml.
when_to_use: >-
  Trigger when the user wants a new deterministic Robot test (connectivity,
  config validation, data-format or computation checks) that needs no LLM and no
  custom Python, or asks how to write a tier:0 test.
---

# Creating a tier:0 Robot Framework test

## When to Use

Use this skill when creating a **pure Robot Framework test** that verifies behavior
using only deterministic RF built-in assertions. No LLM calls, no Python-backed
keywords, no non-deterministic behavior.

**Good candidates for tier:0:**
- Infrastructure connectivity checks (DB alive, service reachable)
- Configuration validation (env vars set, files exist)
- Data format validation (regex matching, string equality)
- Deterministic computation checks (math, string ops via `Evaluate`)
- File system checks (file exists, file contains expected content)

## Required Tags

Every tier:0 test must have exactly these two tags:

```robot
[Tags]    tier:0    verify:robot
```

Or set at the suite level in `__init__.robot`:

```robot
Test Tags    tier:0    verify:robot
```

## Step-by-Step

### 1. Choose a Domain Directory

Place your test in `robot/<domain>/tests/`. If creating a new domain:

```
robot/<domain>/
    __init__.robot          # Optional: suite-level settings and tags
    <domain>.resource       # Optional: shared keywords for this domain
    tests/
        __init__.robot      # Optional: test-level settings
        test_<name>.robot   # Your test file
```

### 2. Create the Test File

```robot
*** Settings ***
Documentation     <One-line description of what this suite tests>
Library           Collections
Library           OperatingSystem
Library           String

*** Variables ***
${EXPECTED_VALUE}    42

*** Test Cases ***
Descriptive Test Name Here
    [Documentation]    <What this test verifies and why>
    [Tags]    tier:0    verify:robot
    # Arrange
    ${result}=    Set Variable    42
    # Assert
    Should Be Equal As Strings    ${result}    ${EXPECTED_VALUE}

Another Test Name
    [Documentation]    <Description>
    [Tags]    tier:0    verify:robot
    ${output}=    Evaluate    2 + 2
    Should Be Equal As Integers    ${output}    4
```

### 3. Allowed Keywords (Tier:0 Only)

Only use RF built-in assertion keywords:

| Keyword | Use Case |
|---------|----------|
| `Should Be Equal` | Exact string match |
| `Should Be Equal As Integers` | Numeric equality |
| `Should Be Equal As Numbers` | Float equality |
| `Should Be True` | Boolean expression |
| `Should Contain` | Substring check |
| `Should Not Contain` | Negative substring |
| `Should Match Regexp` | Regex pattern |
| `Should Not Be Empty` | Non-empty check |
| `Should Start With` / `Should End With` | Prefix/suffix |
| `File Should Exist` | File presence |
| `Length Should Be` | Collection/string length |
| `List Should Contain Value` | List membership |
| `Dictionary Should Contain Key` | Dict key check |

**Prohibited in tier:0:**
- `LLM.Ask LLM`, `LLM.Grade Answer` (these are tier:2+)
- Any custom Python keyword library from `src/rfc/` that calls LLMs
- `Sleep` for timing-dependent assertions
- Network calls to external services (use mocks or skip)

### 4. Using Shared Resources

If your domain has shared keywords, create a `.resource` file:

```robot
*** Settings ***
Documentation     Shared keywords for <domain> tests

*** Variables ***
${SOME_CONSTANT}    value

*** Keywords ***
My Reusable Check
    [Arguments]    ${input}    ${expected}
    Should Be Equal    ${input}    ${expected}
```

Then import it in your test:

```robot
*** Settings ***
Resource    ../<domain>.resource
```

### 5. Register the Suite

Add to **both** config files:

**`config/test_suites.yaml`** — under `test_suites:`:
```yaml
  <domain>:
    label: "<Human-Readable Name>"
    path: "robot/<domain>/tests"
    description: "<What this suite tests>"
```

**`config/local_models.yaml`** — under `test_suites:`:
```yaml
  - name: "<domain>"
    path: "robot/<domain>/tests/"
    description: "<What this suite tests>"
    timeout_seconds: 60
```

### 6. Verify

```bash
# Validate Robot syntax (no execution)
make robot-dryrun

# Run pre-commit checks
pre-commit run --all-files
```

## Reference Examples

- `robot/superset/tests/__init__.robot` — suite-level `tier:0 verify:robot` tags
- `robot/superset/tests/connection.robot` — infrastructure check pattern (note: these
  specific tests are tagged tier:6 because they do data collection, but the *pattern*
  of using Python keywords for infrastructure checks is reusable)

## Common Pitfalls

1. **Forgetting tags** — every test needs both `tier:0` and `verify:robot`
2. **Importing LLM keywords** — if your `*** Settings ***` imports
   `rfc.keywords.LLMKeywords`, it's not tier:0
3. **Non-deterministic inputs** — `Generate Random Integer` is fine for *inputs*,
   but the *assertion* must be deterministic (compare against `Evaluate`)
4. **Not registering** — new suites must be in both `test_suites.yaml` and
   `local_models.yaml`, or they won't run in CI or local cron
