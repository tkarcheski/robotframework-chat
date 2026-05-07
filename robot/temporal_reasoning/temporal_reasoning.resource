*** Settings ***
Documentation     Shared keywords for temporal reasoning tests.
...
...               Provides reusable wrappers around TemporalReasoningKeywords
...               so individual test files stay focused on test data.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    TR
Variables         ${CURDIR}/variables/temporal_scenarios.yaml

*** Keywords ***
Ask Numeric And Pass
    [Documentation]    Ask a numeric temporal question and assert it passes.
    [Arguments]    ${scenario}
    ${result}=    TR.Ask Temporal Numeric Question
    ...    ${scenario}[question]    ${scenario}[expected]
    TR.Assert Temporal Result Passed    ${result}
    Log    ${result}[reason]
    RETURN    ${result}

Ask Date And Pass
    [Documentation]    Ask a date arithmetic question and assert it passes.
    [Arguments]    ${scenario}
    ${result}=    TR.Ask Temporal Date Question
    ...    ${scenario}[question]    ${scenario}[expected]
    TR.Assert Temporal Result Passed    ${result}
    Log    ${result}[reason]
    RETURN    ${result}

Ask Weekday And Pass
    [Documentation]    Ask a day-of-week question and assert it passes.
    [Arguments]    ${scenario}
    ${result}=    TR.Ask Temporal Weekday Question
    ...    ${scenario}[question]    ${scenario}[expected]
    TR.Assert Temporal Result Passed    ${result}
    Log    ${result}[reason]
    RETURN    ${result}
