*** Settings ***
Documentation     Shared keywords and configuration for extraction tests.

Library           rfc.extraction_keywords.ExtractionKeywords    WITH NAME    Extraction
Variables         ${CURDIR}/variables/entity_scenarios.yaml
Variables         ${CURDIR}/variables/key_value_scenarios.yaml

*** Keywords ***
Assert Entity Extracted Correctly
    [Documentation]    Extract a single entity and assert the expected value is present.
    [Arguments]    ${scenario}
    ${result}=    Extraction.Extract And Verify Entity
    ...    ${scenario}[text]
    ...    ${scenario}[question]
    ...    ${scenario}[expected]
    Log    Extracted: ${result}[extracted]
    Log    Expected: ${result}[expected]
    Log    Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Extraction failed for '${scenario}[id]' (${scenario}[name]): extracted '${result}[extracted]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Key Value Extracted Correctly
    [Documentation]    Extract a key-value pair and assert the expected value is present.
    [Arguments]    ${scenario}
    ${result}=    Extraction.Extract Key Value And Verify
    ...    ${scenario}[text]
    ...    ${scenario}[attribute]
    ...    ${scenario}[expected]
    Log    Extracted: ${result}[extracted]
    Log    Expected: ${result}[expected]
    Log    Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Key-value extraction failed for '${scenario}[id]' (${scenario}[name]): extracted '${result}[extracted]' but expected '${result}[expected]'
    RETURN    ${result}
