*** Settings ***
Documentation     Duration Calculation Tests
...
...               Asks the LLM to convert between time units (hours to minutes,
...               days to hours, etc.) and verifies the integer answer extracted
...               from the first line of the response.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    duration    tier:1    verify:python
Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***
Three Hours Is 180 Minutes
    [Documentation]    3 hours × 60 minutes/hour = 180 minutes.
    [Tags]    tier:1    verify:python    time_units
    Assert Duration Calculation Correct    ${DURATION_CASES}[0]

Five Minutes Is 300 Seconds
    [Documentation]    5 minutes × 60 seconds/minute = 300 seconds.
    [Tags]    tier:1    verify:python    time_units
    Assert Duration Calculation Correct    ${DURATION_CASES}[1]

Two Days Is 48 Hours
    [Documentation]    2 days × 24 hours/day = 48 hours.
    [Tags]    tier:1    verify:python    time_units
    Assert Duration Calculation Correct    ${DURATION_CASES}[2]

63 Days Contains 9 Complete Weeks
    [Documentation]    63 ÷ 7 = 9 complete weeks exactly.
    [Tags]    tier:1    verify:python    time_units
    Assert Duration Calculation Correct    ${DURATION_CASES}[3]

One Day Is 1440 Minutes
    [Documentation]    1 day × 24 hours × 60 minutes = 1440 minutes.
    [Tags]    tier:1    verify:python    time_units
    Assert Duration Calculation Correct    ${DURATION_CASES}[4]

One Hour Is 3600 Seconds
    [Documentation]    1 hour × 60 minutes × 60 seconds = 3600 seconds.
    [Tags]    tier:1    verify:python    time_units
    Assert Duration Calculation Correct    ${DURATION_CASES}[5]
