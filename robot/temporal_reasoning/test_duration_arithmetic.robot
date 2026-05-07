*** Settings ***
Documentation     Duration and counting temporal reasoning tests.
...
...               Verifies the LLM can answer basic questions about
...               day counts, hour totals, leap-year awareness, and
...               week calculations.  All answers are deterministic
...               integers extracted by regex — no secondary LLM grader.

Resource          temporal_reasoning.resource
Default Tags      temporal_reasoning    duration    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Days In January
    [Documentation]    The month of January always has 31 days.
    [Tags]    months    basic
    Ask Numeric And Pass    ${DURATION_SCENARIOS}[0]

Hours In Three Days
    [Documentation]    3 days × 24 hours = 72 hours.
    [Tags]    hours    basic
    Ask Numeric And Pass    ${DURATION_SCENARIOS}[1]

February Days In Leap Year 2024
    [Documentation]    2024 is a leap year so February has 29 days.
    [Tags]    leap_year
    Ask Numeric And Pass    ${DURATION_SCENARIOS}[2]

Days Between January 1 And February 1 2024
    [Documentation]    31 days between Jan 1 and Feb 1, 2024.
    [Tags]    date_diff
    Ask Numeric And Pass    ${DURATION_SCENARIOS}[3]

Weeks In Twenty-Eight Days
    [Documentation]    28 ÷ 7 = 4 weeks exactly.
    [Tags]    weeks    basic
    Ask Numeric And Pass    ${DURATION_SCENARIOS}[4]
