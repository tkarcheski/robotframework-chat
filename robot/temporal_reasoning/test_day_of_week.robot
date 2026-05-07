*** Settings ***
Documentation     Day-of-week temporal reasoning tests.
...
...               Tests whether the LLM can determine what day of the
...               week a specific calendar date falls on.

Resource          temporal_reasoning.resource
Default Tags      temporal_reasoning    weekday    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Day Of Week July 4 2025
    [Documentation]    July 4, 2025 is a Friday.
    [Tags]    weekday    us_holiday
    Ask Weekday And Pass    ${WEEKDAY_SCENARIOS}[0]

Day Of Week January 1 2024
    [Documentation]    January 1, 2024 is a Monday.
    [Tags]    weekday    new_year
    Ask Weekday And Pass    ${WEEKDAY_SCENARIOS}[1]
