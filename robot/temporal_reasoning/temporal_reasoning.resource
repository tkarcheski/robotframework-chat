*** Settings ***
Documentation     Shared keywords and configuration for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    Temporal
Variables         ${CURDIR}/variables/time_arithmetic.yaml
Variables         ${CURDIR}/variables/calendar_arithmetic.yaml
Variables         ${CURDIR}/variables/event_chronology.yaml

*** Keywords ***
Assert Temporal Arithmetic Correct
    [Documentation]    Evaluate a temporal arithmetic question and assert the model answered correctly.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Evaluate Temporal Arithmetic
    ...    ${scenario}[question]
    ...    ${scenario}[expected_value]
    Log    Extracted: ${result}[extracted_value] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM gave '${result}[extracted_value]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Chronological Order Correct
    [Documentation]    Evaluate an event ordering question and assert the model chose the correct event.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Evaluate Chronological Order
    ...    ${scenario}[question]
    ...    ${scenario}[expected_letter]
    Log    Chosen: ${result}[chosen_letter] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM chose '${result}[chosen_letter]' but expected '${result}[expected]' for: ${scenario}[id]
    RETURN    ${result}
