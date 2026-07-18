*** Settings ***
Documentation     Structured Output Format Tests
...
...               Ask the LLM for JSON, YAML, and CSV output with a schema.
...               Parse the result programmatically and assert it validates
...               against the schema. Uses score: tags for partial-credit grading.

Resource          format.resource

Test Tags         structured-output    tier:1    verify:python    axis:model

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

JSON Adversarial Prose Resistance
    [Documentation]    Prompt embeds adversarial conversational pressure while
    ...    requiring raw JSON only. Probes whether the model resists prepending
    ...    explanation and emits programmatically parseable JSON. Prose before
    ...    unfenced JSON fails json.loads and scores 0.
    [Tags]    json    score:partial
    ${scenario}=    Set Variable    ${JSON_SCENARIOS}[3]
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

YAML Special Character String Values
    [Documentation]    Require string values carrying YAML-special sequences
    ...    (a colon followed by a space, and a leading '#') that force quoting
    ...    or block scalars. Naive inline emission produces invalid YAML, which
    ...    fails to parse and scores 0.
    [Tags]    yaml    score:partial
    ${scenario}=    Set Variable    ${YAML_SCENARIOS}[2]
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

CSV Escaping And Quoting Rules
    [Documentation]    Require data fields containing commas, which must be
    ...    quoted per RFC 4180. Unquoted fields split into extra columns and
    ...    fail the strict column-count check; graded at min_score=1.0 so a
    ...    quoting failure is a hard fail, not partial credit.
    [Tags]    csv    score:partial
    ${scenario}=    Set Variable    ${CSV_SCENARIOS}[2]
    Ask And Validate CSV
    ...    ${scenario}[prompt]
    ...    ${scenario}[expected_columns]
    ...    ${scenario}[min_rows]
    ...    min_score=1.0

# ---------- Batch ----------

Batch JSON Validation - All Scenarios
    [Documentation]    Validate all JSON scenarios in sequence.
    [Tags]    batch    json    score:partial
    FOR    ${scenario}    IN    @{JSON_SCENARIOS}
        Ask And Validate JSON    ${scenario}[prompt]    ${scenario}[expected_keys]    min_score=0.5
    END
