*** Settings ***
Documentation     Shared keywords and configuration for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    Temporal
Variables         ${CURDIR}/variables/date_arithmetic_cases.yaml
Variables         ${CURDIR}/variables/duration_cases.yaml
Variables         ${CURDIR}/variables/event_ordering_cases.yaml

*** Keywords ***
Assert Date Arithmetic Correct
    [Documentation]    Ask the LLM a date arithmetic question and assert the numeric answer matches.
    [Arguments]    ${case}
    ${result}=    Temporal.Evaluate Date Arithmetic
    ...    ${case}[question]
    ...    ${case}[expected_answer]
    Log    Extracted: ${result}[extracted_answer] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Date arithmetic wrong for '${case}[name]': extracted ${result}[extracted_answer], expected ${result}[expected]
    RETURN    ${result}

Assert Duration Calculation Correct
    [Documentation]    Ask the LLM a duration calculation and assert the numeric answer matches.
    [Arguments]    ${case}
    ${result}=    Temporal.Evaluate Duration Calculation
    ...    ${case}[question]
    ...    ${case}[expected_answer]
    Log    Extracted: ${result}[extracted_answer] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Duration calculation wrong for '${case}[name]': extracted ${result}[extracted_answer], expected ${result}[expected]
    RETURN    ${result}

Assert Earliest Event Correct
    [Documentation]    Ask the LLM which of four events is earliest and assert the letter matches.
    [Arguments]    ${case}
    ${result}=    Temporal.Check Earliest Event
    ...    ${case}[event_a]
    ...    ${case}[event_b]
    ...    ${case}[event_c]
    ...    ${case}[event_d]
    ...    ${case}[expected_letter]
    Log    Chosen: ${result}[chosen_letter] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Event ordering wrong for '${case}[name]': chose ${result}[chosen_letter], expected ${result}[expected]
    RETURN    ${result}
