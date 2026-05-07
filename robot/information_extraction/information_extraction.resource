*** Settings ***
Documentation     Shared keywords for information extraction tests.
...
...               Wraps ExtractionKeywords with pass/fail assertion
...               helpers for clean test bodies.

Library           rfc.extraction_keywords.ExtractionKeywords    WITH NAME    EX
Variables         ${CURDIR}/variables/extraction_scenarios.yaml

*** Keywords ***
Extract Entities And Pass
    [Documentation]    Ask the LLM to extract entities and assert all expected ones appear.
    [Arguments]    ${scenario}    ${min_score}=1.0
    ${result}=    EX.Ask And Extract Named Entities
    ...    context=${scenario}[context]
    ...    expected_entities=${scenario}[expected_entities]
    ...    entity_type=${scenario}[entity_type]
    ...    min_score=${min_score}
    EX.Assert Extraction Passed    ${result}    label=${scenario}[label]
    Log    ${result}[reason]
    RETURN    ${result}

Extract Numeric Fact And Pass
    [Documentation]    Ask the LLM to find a numeric value in text and assert correctness.
    [Arguments]    ${scenario}
    ${result}=    EX.Ask And Extract Numeric Fact
    ...    context=${scenario}[context]
    ...    question=${scenario}[question]
    ...    expected_value=${scenario}[expected_value]
    EX.Assert Extraction Passed    ${result}    label=${scenario}[label]
    Log    ${result}[reason]
    RETURN    ${result}

Extract Key Values And Pass
    [Documentation]    Ask the LLM to extract key-value pairs and assert expected ones appear.
    [Arguments]    ${scenario}    ${min_score}=1.0
    ${result}=    EX.Ask And Extract Key Value Pairs
    ...    context=${scenario}[context]
    ...    expected_pairs=${scenario}[expected_pairs]
    ...    min_score=${min_score}
    EX.Assert Extraction Passed    ${result}    label=${scenario}[label]
    Log    ${result}[reason]
    RETURN    ${result}
