*** Settings ***
Documentation     Structured Output Format Tests
...
...               Ask the LLM for JSON, YAML, and CSV output with a schema.
...               Parse the result programmatically and assert it validates
...               against the schema. Uses score: tags for partial-credit grading.

Resource          format.resource

Default Tags      structured-output    tier:1    verify:python

*** Test Cases ***

# ---------- JSON ----------

JSON Person Object
    [Documentation]    Ask for a JSON object with name, age, email keys.
    [Tags]    json    score:partial
    ${scenario}=    Set Variable    ${JSON_SCENARIOS}[0]
    Ask And Validate JSON    ${scenario}[prompt]    ${scenario}[expected_keys]    min_score=0.5

JSON Product Array
    [Documentation]    Ask for a JSON array of products with id, name, price keys.
    [Tags]    json    score:partial
    ${scenario}=    Set Variable    ${JSON_SCENARIOS}[1]
    Ask And Validate JSON    ${scenario}[prompt]    ${scenario}[expected_keys]    min_score=0.5

JSON Address Object
    [Documentation]    Ask for a JSON object with street, city, state, zip keys.
    [Tags]    json    score:partial
    ${scenario}=    Set Variable    ${JSON_SCENARIOS}[2]
    Ask And Validate JSON    ${scenario}[prompt]    ${scenario}[expected_keys]    min_score=0.5

# ---------- YAML ----------

YAML Server Config
    [Documentation]    Ask for YAML with host, port, debug, workers keys.
    [Tags]    yaml    score:partial
    ${scenario}=    Set Variable    ${YAML_SCENARIOS}[0]
    Ask And Validate YAML    ${scenario}[prompt]    ${scenario}[expected_keys]    min_score=0.5

YAML Database Config
    [Documentation]    Ask for YAML with engine, host, port, name, user keys.
    [Tags]    yaml    score:partial
    ${scenario}=    Set Variable    ${YAML_SCENARIOS}[1]
    Ask And Validate YAML    ${scenario}[prompt]    ${scenario}[expected_keys]    min_score=0.5

# ---------- CSV ----------

CSV Employee Table
    [Documentation]    Ask for CSV with 3 columns and 3 data rows.
    [Tags]    csv    score:partial
    ${scenario}=    Set Variable    ${CSV_SCENARIOS}[0]
    Ask And Validate CSV
    ...    ${scenario}[prompt]
    ...    ${scenario}[expected_columns]
    ...    ${scenario}[min_rows]
    ...    min_score=0.5

CSV Inventory Table
    [Documentation]    Ask for CSV with 4 columns and 4 data rows.
    [Tags]    csv    score:partial
    ${scenario}=    Set Variable    ${CSV_SCENARIOS}[1]
    Ask And Validate CSV
    ...    ${scenario}[prompt]
    ...    ${scenario}[expected_columns]
    ...    ${scenario}[min_rows]
    ...    min_score=0.5

# ---------- Batch ----------

Batch JSON Validation - All Scenarios
    [Documentation]    Validate all JSON scenarios in sequence.
    [Tags]    batch    json    score:partial
    FOR    ${scenario}    IN    @{JSON_SCENARIOS}
        Ask And Validate JSON    ${scenario}[prompt]    ${scenario}[expected_keys]    min_score=0.5
    END
