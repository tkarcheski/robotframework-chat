*** Settings ***
Documentation     Shared keywords and configuration for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    Temporal
Variables         ${CURDIR}/variables/calendar_scenarios.yaml
Variables         ${CURDIR}/variables/duration_scenarios.yaml
Variables         ${CURDIR}/variables/sequence_scenarios.yaml

*** Keywords ***
Assert Calendar Answer Correct
    [Documentation]    Ask a calendar arithmetic question and assert the correct
    ...                month and day appear in the LLM's answer.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Check Calendar Answer
    ...    ${scenario}[question]
    ...    ${scenario}[expected_month]
    ...    ${scenario}[expected_day]
    Log    Month found: ${result}[correct] | Expected: ${result}[expected_month] ${result}[expected_day]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Calendar answer incorrect for: ${scenario}[question]\nExpected: ${result}[expected_month] ${result}[expected_day]\nGot: ${result}[response]
    RETURN    ${result}

Assert Duration Answer Correct
    [Documentation]    Ask a duration question and assert the expected integer
    ...                appears in the LLM's answer.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Check Duration Answer
    ...    ${scenario}[question]
    ...    ${scenario}[expected_count]
    Log    Count found: ${result}[correct] | Expected: ${result}[expected_count]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Duration answer incorrect for: ${scenario}[question]\nExpected: ${result}[expected_count]\nGot: ${result}[response]
    RETURN    ${result}

Assert Sequence Order Correct
    [Documentation]    Ask the LLM to order events and assert anchor_first
    ...                appears before anchor_last in the output.
    [Arguments]    ${scenario}
    ${result}=    Temporal.Check Sequence Order
    ...    ${scenario}[question]
    ...    ${scenario}[anchor_first]
    ...    ${scenario}[anchor_last]
    Log    Order correct: ${result}[correct] | First: ${result}[anchor_first] | Last: ${result}[anchor_last]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Sequence order incorrect for: ${scenario}[question]\nExpected '${result}[anchor_first]' before '${result}[anchor_last]'\nGot: ${result}[response]
    RETURN    ${result}
