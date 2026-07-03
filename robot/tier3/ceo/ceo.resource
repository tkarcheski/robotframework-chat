*** Settings ***
Documentation     Common keywords and variables for CEO agent tests

Library           rfc.ceo_keywords.CEOKeywords
Variables         ${CURDIR}/variables/stage_inputs.yaml
Variables         ${CURDIR}/variables/grading_rubrics.yaml

*** Variables ***
# Default test configuration
${CEO_DEFAULT_DOMAIN}         smart home IoT devices
${CEO_IDEA_COUNT}             3

*** Keywords ***
Setup CEO Test Environment
    [Documentation]    Initialize the CEO testing environment
    Log    CEO Agent test environment initialized

Cleanup CEO Tests
    [Documentation]    Cleanup after CEO tests
    Clear Web Cache
    Log    CEO Agent tests completed

Run Stage And Validate
    [Documentation]    Run a pipeline stage, validate structure, and grade output
    [Arguments]    ${stage_name}    ${output}    ${rubric}
    Validate Stage Structure    ${stage_name}    ${output}
    ${grade}=    Grade Stage Output    ${stage_name}    ${output}    ${rubric}
    Should Be True    ${grade}[passed]
    ...    Stage ${stage_name} failed multi-LLM grading: ${grade}[reasons]
    RETURN    ${grade}
