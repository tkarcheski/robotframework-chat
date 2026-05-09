*** Settings ***
Documentation     Date and time arithmetic tests.
...
...               Asks the LLM to compute a specific integer answer to a
...               date/time question.  The answer is extracted from the first
...               line of the response and compared to the known-correct value,
...               making these Tier 1 / verify:python tests.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    date_arithmetic    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

February 2024 Has 29 Days
    [Documentation]    2024 is a leap year; February has 29 days.
    [Tags]    tier:1    verify:python    leap_year
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[0]
    Assert Date Calculation Correct    ${s}

Three Days Have 72 Hours
    [Documentation]    3 days × 24 hours = 72 hours.
    [Tags]    tier:1    verify:python    unit_conversion
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[1]
    Assert Date Calculation Correct    ${s}

55 Years Passed Between 1969 And 2024
    [Documentation]    2024 − 1969 = 55 full years.
    [Tags]    tier:1    verify:python    year_span
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[2]
    Assert Date Calculation Correct    ${s}

Person Born 1990 Is 34 In 2024
    [Documentation]    A person born on 1 January 1990 turns 34 on 1 January 2024.
    [Tags]    tier:1    verify:python    age_calculation
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[3]
    Assert Date Calculation Correct    ${s}

Year 2023 Has 365 Days
    [Documentation]    2023 is not a leap year; it has 365 days.
    [Tags]    tier:1    verify:python    days_in_year
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[4]
    Assert Date Calculation Correct    ${s}

Two Hours Have 120 Minutes
    [Documentation]    2 hours × 60 minutes = 120 minutes.
    [Tags]    tier:1    verify:python    unit_conversion
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[5]
    Assert Date Calculation Correct    ${s}
