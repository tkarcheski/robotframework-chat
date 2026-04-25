*** Settings ***
Documentation     JSON Schema Validation Tests
...
...               Tests LLM ability to generate JSON conforming to
...               specified schemas. Tests include basic validation,
...               retry logic, and optional model comparison.

Resource          ../json_schema.resource

Default Tags      json-schema    tier:2    verify:llm

*** Test Cases ***

Basic Profile JSON Validation
    [Documentation]    Ask for a user profile in JSON and validate the schema.
    [Tags]    basic    score:partial
    Setup JSON Schema Test Environment
    ${scenario}=    Set Variable    ${basic_profile}
    Ask For JSON With Schema
    ...    ${scenario}[prompt]
    ...    ${scenario}[schema]
    ...    schema_name=${scenario}[name]
    ...    min_score=${scenario}[min_score]

Product List JSON Validation
    [Documentation]    Ask for a product list in JSON and validate schema.
    [Tags]    array    score:partial
    Setup JSON Schema Test Environment
    ${scenario}=    Set Variable    ${product_list}
    Ask For JSON With Schema
    ...    ${scenario}[prompt]
    ...    ${scenario}[schema]
    ...    schema_name=${scenario}[name]
    ...    min_score=${scenario}[min_score]

Configuration Object JSON Validation
    [Documentation]    Ask for a configuration object and validate nested structure.
    [Tags]    nested    score:partial
    Setup JSON Schema Test Environment
    ${scenario}=    Set Variable    ${config_object}
    Ask For JSON With Schema
    ...    ${scenario}[prompt]
    ...    ${scenario}[schema]
    ...    schema_name=${scenario}[name]
    ...    min_score=${scenario}[min_score]

JSON Validation With Retry Logic
    [Documentation]    Test JSON schema validation with automatic retry on failure.
    [Tags]    retry    score:partial
    Setup JSON Schema Test Environment
    ${scenario}=    Set Variable    ${basic_profile}
    ${score}    ${attempt}=    Ask For JSON With Retries
    ...    ${scenario}[prompt]
    ...    ${scenario}[schema]
    ...    schema_name=${scenario}[name]
    ...    max_retries=5
    Log    Achieved score ${score} on attempt ${attempt}

Batch Schema Validation
    [Documentation]    Validate all schema scenarios in sequence.
    [Tags]    batch    score:partial
    Setup JSON Schema Test Environment
    @{all_scenarios}=    Create List
    ...    ${basic_profile}
    ...    ${product_list}
    ...    ${config_object}
    Test JSON Schema Across Scenarios    @{all_scenarios}
