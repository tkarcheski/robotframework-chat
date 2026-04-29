*** Settings ***
Documentation     Shared keywords for JSON schema validation tests.
...
...               Provides keywords for asking the LLM to generate JSON
...               conforming to schemas and validating the results.

Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           rfc.json_schema_keywords.JSONSchemaKeywords    WITH NAME    JSONSchema
Variables         ${CURDIR}/variables/schema_scenarios.yaml

*** Variables ***
${SCHEMA_MAX_TOKENS}    512

*** Keywords ***
Setup JSON Schema Test Environment
    [Documentation]    Initialize LLM for JSON schema validation tests.
    LLM.Set LLM Parameters    temperature=0.0    max_tokens=${SCHEMA_MAX_TOKENS}
    Log    JSON schema test environment initialized

Ask For JSON With Schema
    [Documentation]    Ask LLM to generate JSON and validate against schema.
    ...    Returns the validation score (0.0–1.0).
    [Arguments]    ${prompt}    ${schema}    ${schema_name}=custom    ${min_score}=0.5
    ${response}=    LLM.Ask LLM    ${prompt}
    Should Not Be Empty    ${response}    LLM returned empty response
    ${score}=    JSONSchema.Validate JSON With Schema    ${response}    ${schema}    ${schema_name}
    Should Be True    ${score} >= ${min_score}
    ...    JSON schema validation score ${score} below threshold ${min_score}
    RETURN    ${score}

Ask For JSON With Retries
    [Documentation]    Ask LLM to generate JSON with retry logic.
    ...    Measures how many attempts needed for successful validation.
    [Arguments]    ${prompt}    ${schema}    ${schema_name}=custom    ${max_retries}=5
    ${score}    ${attempt}=    JSONSchema.Validate JSON With Retries    ${prompt}    ${schema}    ${schema_name}    ${max_retries}
    Should Be True    ${score} == 1.0    JSON schema validation failed after ${attempt} attempts with score ${score}
    Log    JSON schema validation succeeded on attempt ${attempt} with score ${score}
    RETURN    ${score}    ${attempt}

Test JSON Schema Across Scenarios
    [Documentation]    Test multiple JSON schema scenarios in sequence.
    [Arguments]    @{scenarios}
    FOR    ${scenario}    IN    @{scenarios}
        Ask For JSON With Schema
        ...    ${scenario}[prompt]
        ...    ${scenario}[schema]
        ...    schema_name=${scenario}[name]
        ...    min_score=${scenario}[min_score]
    END
