*** Settings ***
Documentation     Calendar Arithmetic Tests
...
...               Asks the LLM to reason about the Gregorian calendar: days in
...               months, leap-year rules, and day-of-year offsets. Expected
...               answers are exact integers verified deterministically by Python
...               (Tier 1 / verify:python).

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    calendar_arithmetic    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Days In February Common Year
    [Documentation]    February has 28 days in a non-leap year.
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[0]
    Assert Temporal Arithmetic Correct    ${s}

Days In February Leap Year
    [Documentation]    February has 29 days in a leap year.
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[1]
    Assert Temporal Arithmetic Correct    ${s}

Combined Days In January And February
    [Documentation]    31 + 28 = 59 days through end of February in a common year.
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[2]
    Assert Temporal Arithmetic Correct    ${s}

Days In Q1 Common Year
    [Documentation]    31 + 28 + 31 = 90 days in Q1 of a common year.
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[3]
    Assert Temporal Arithmetic Correct    ${s}

Days In April
    [Documentation]    April has 30 days (thirty days hath April...).
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[4]
    Assert Temporal Arithmetic Correct    ${s}

Day Number Of March First
    [Documentation]    March 1 is day 60 in a common year (31 + 28 + 1 = 60).
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[5]
    Assert Temporal Arithmetic Correct    ${s}

Day Number Of July First
    [Documentation]    July 1 is day 182 in a common year (31+28+31+30+31+30+1 = 182).
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[6]
    Assert Temporal Arithmetic Correct    ${s}

Days In Q2 Common Year
    [Documentation]    30 + 31 + 30 = 91 days in Q2 of a common year.
    [Tags]    tier:1    verify:python    calendar
    ${s}=    Set Variable    ${CALENDAR_ARITHMETIC_SCENARIOS}[7]
    Assert Temporal Arithmetic Correct    ${s}
