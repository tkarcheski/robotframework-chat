*** Settings ***
Documentation     JSON Schema Validation Tests
...
...               Tests LLM ability to generate JSON conforming to
...               specified schemas. Tests include basic validation,
...               retry logic, and optional model comparison.

Resource          ../json_schema.resource
Suite Setup       Setup JSON Schema Test Environment

Test Tags         json-schema    tier:2    verify:llm

*** Test Cases ***

Basic Profile JSON Validation
    [Tags]    basic    score:partial
    Validate Scenario    ${basic_profile}

Product List JSON Validation
    [Tags]    array    score:partial
    Validate Scenario    ${product_list}

Configuration Object JSON Validation
    [Tags]    nested    score:partial
    Validate Scenario    ${config_object}

JSON Validation With Retry Logic
    [Documentation]    Asks for JSON and retries with escalating prompts on failure.
    [Tags]    retry    score:partial
    ${score}    ${attempt}=    Ask For JSON With Retries
    ...    ${basic_profile}[prompt]
    ...    ${basic_profile}[schema]
    ...    schema_name=${basic_profile}[name]
    ...    max_retries=5
    Log    Achieved score ${score} on attempt ${attempt}

Batch Schema Validation
    [Documentation]    Validate all schema scenarios in sequence.
    [Tags]    batch    score:partial
    @{all_scenarios}=    Create List    ${basic_profile}    ${product_list}    ${config_object}
    Test JSON Schema Across Scenarios    @{all_scenarios}

*** Keywords ***
Validate Scenario
    [Arguments]    ${scenario}
    Ask For JSON With Schema
    ...    ${scenario}[prompt]
    ...    ${scenario}[schema]
    ...    schema_name=${scenario}[name]
    ...    min_score=${scenario}[min_score]
