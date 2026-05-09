*** Settings ***
Documentation     Time Arithmetic Tests
...
...               Asks the LLM to perform conversions and calculations involving
...               seconds, minutes, and hours. Expected answers are exact integers
...               verified deterministically by Python (Tier 1 / verify:python).

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    time_arithmetic    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Seconds In One Hour
    [Documentation]    60 × 60 = 3600 seconds per hour.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[0]
    Assert Temporal Arithmetic Correct    ${s}

Minutes In One Day
    [Documentation]    24 × 60 = 1440 minutes per day.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[1]
    Assert Temporal Arithmetic Correct    ${s}

Hours In One Week
    [Documentation]    7 × 24 = 168 hours per week.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[2]
    Assert Temporal Arithmetic Correct    ${s}

Two Hours Forty-Five Minutes In Minutes
    [Documentation]    2 × 60 + 45 = 165 minutes.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[3]
    Assert Temporal Arithmetic Correct    ${s}

Eight Hours Thirty Minutes In Minutes
    [Documentation]    8 × 60 + 30 = 510 minutes.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[4]
    Assert Temporal Arithmetic Correct    ${s}

Seconds In Ninety Minutes
    [Documentation]    90 × 60 = 5400 seconds.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[5]
    Assert Temporal Arithmetic Correct    ${s}

Flight Duration In Minutes
    [Documentation]    6 × 60 + 40 = 400 minutes for a 6h 40m flight.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[6]
    Assert Temporal Arithmetic Correct    ${s}

Four Day Work Week In Hours
    [Documentation]    4 × 8 = 32 total working hours.
    [Tags]    tier:1    verify:python    duration
    ${s}=    Set Variable    ${TIME_ARITHMETIC_SCENARIOS}[7]
    Assert Temporal Arithmetic Correct    ${s}
