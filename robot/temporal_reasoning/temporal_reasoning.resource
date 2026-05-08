*** Settings ***
Documentation     Shared keywords and configuration for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    Temporal
Variables         ${CURDIR}/variables/date_arithmetic_scenarios.yaml
Variables         ${CURDIR}/variables/sequence_ordering_scenarios.yaml
Variables         ${CURDIR}/variables/duration_scenarios.yaml

*** Keywords ***
Assert Date Arithmetic Correct
    [Documentation]    Solve a date arithmetic problem and assert the answer is correct.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Solve Date Arithmetic
    ...    ${scenario}[question]
    ...    ${scenario}[expected]
    ...    ${scenario}[tolerance]
    Log    Answer: ${result}[answer] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM answered '${result}[answer]' but expected '${result}[expected]' (tolerance: ${scenario}[tolerance]) for scenario '${scenario}[id]'
    RETURN    ${result}

Assert Event Ordering Correct
    [Documentation]    Check chronological event ordering and assert it is correct.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Check Event Ordering
    ...    ${scenario}[events]
    ...    ${scenario}[expected_order]
    Log    Actual: ${result}[actual_order] | Expected: ${result}[expected_order] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM gave order '${result}[actual_order]' but expected '${result}[expected_order]' for scenario '${scenario}[id]'
    RETURN    ${result}

Assert Duration Correct
    [Documentation]    Estimate a well-known duration and assert it is within tolerance.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Estimate Duration
    ...    ${scenario}[question]
    ...    ${scenario}[expected]
    ...    ${scenario}[tolerance]
    Log    Answer: ${result}[answer] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM answered '${result}[answer]' but expected '${result}[expected]' ±${scenario}[tolerance] for scenario '${scenario}[id]'
    RETURN    ${result}
