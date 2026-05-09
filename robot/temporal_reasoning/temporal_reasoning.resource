*** Settings ***
Documentation     Shared keywords and configuration for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    Temporal
Variables         ${CURDIR}/variables/ordering_scenarios.yaml
Variables         ${CURDIR}/variables/date_arithmetic_scenarios.yaml
Variables         ${CURDIR}/variables/sequence_scenarios.yaml

*** Keywords ***
Assert Temporal Order Correct
    [Documentation]    Ask the LLM whether Event A is BEFORE or AFTER Event B and
    ...                assert the extracted verdict matches the expected answer.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Evaluate Temporal Order
    ...    ${scenario}[event_a]
    ...    ${scenario}[event_b]
    ...    ${scenario}[verdict]
    Log    Verdict: ${result}[verdict] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM gave '${result}[verdict]' for ${scenario}[id] (${scenario}[name]) but expected '${result}[expected]'
    RETURN    ${result}

Assert Date Calculation Correct
    [Documentation]    Ask the LLM a date arithmetic question and assert the
    ...                extracted integer matches the expected answer.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Evaluate Date Calculation
    ...    ${scenario}[question]
    ...    ${scenario}[expected_answer]
    Log    Calculated: ${result}[calculated] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM answered ${result}[calculated] for ${scenario}[id] (${scenario}[name]) but expected ${result}[expected]
    RETURN    ${result}

Assert Event Sequence Correct
    [Documentation]    Ask the LLM to order three events from earliest to latest and
    ...                assert the extracted sequence matches the expected order.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Evaluate Event Sequence
    ...    ${scenario}[event_a]
    ...    ${scenario}[event_b]
    ...    ${scenario}[event_c]
    ...    ${scenario}[expected_sequence]
    Log    Sequence: ${result}[sequence] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM gave sequence ${result}[sequence] for ${scenario}[id] (${scenario}[name]) but expected ${result}[expected]
    RETURN    ${result}
