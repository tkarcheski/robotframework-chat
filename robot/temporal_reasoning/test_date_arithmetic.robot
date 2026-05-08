*** Settings ***
Documentation     Date Arithmetic Tests
...
...               Tests whether an LLM can correctly compute integer answers
...               to date arithmetic questions: day counts, year spans, and
...               basic calendar facts. Answers are extracted deterministically
...               from the first line of the response (Tier 1 / verify:python).

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    date_arithmetic    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Days From Jan 1 To Mar 1 In Non-Leap Year
    [Documentation]    Jan has 31 days, Feb has 28 in a non-leap year: 31 + 28 = 59.
    [Tags]    tier:1    verify:python    calendar    non_leap
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[0]
    Assert Date Arithmetic Correct    ${s}

Days From Jan 1 To Mar 1 In Leap Year
    [Documentation]    Jan has 31 days, Feb has 29 in a leap year: 31 + 29 = 60.
    [Tags]    tier:1    verify:python    calendar    leap
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[1]
    Assert Date Arithmetic Correct    ${s}

Days In A Non-Leap Year
    [Documentation]    A standard year has exactly 365 days.
    [Tags]    tier:1    verify:python    calendar    fundamentals
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[2]
    Assert Date Arithmetic Correct    ${s}

Days In A Leap Year
    [Documentation]    A leap year has exactly 366 days.
    [Tags]    tier:1    verify:python    calendar    fundamentals    leap
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[3]
    Assert Date Arithmetic Correct    ${s}

Complete Weeks In A Year
    [Documentation]    365 / 7 = 52 remainder 1 — there are 52 complete weeks.
    [Tags]    tier:1    verify:python    calendar    fundamentals
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[4]
    Assert Date Arithmetic Correct    ${s}

Days Between March 15 And June 15 In 2024
    [Documentation]    March 15 to June 15 spans exactly 92 days in 2024.
    [Tags]    tier:1    verify:python    date_range
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[5]
    Assert Date Arithmetic Correct    ${s}

Days From Christmas To New Year
    [Documentation]    Dec 25 to Jan 1 (exclusive) = 7 days.
    [Tags]    tier:1    verify:python    date_range
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[6]
    Assert Date Arithmetic Correct    ${s}

Age Calculation For 1990 Birth On Jan 1 2025
    [Documentation]    2025 - 1990 = 35 complete years on the same calendar date.
    [Tags]    tier:1    verify:python    age    calculation
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[7]
    Assert Date Arithmetic Correct    ${s}

Months In A Year
    [Documentation]    There are exactly 12 months in a calendar year.
    [Tags]    tier:1    verify:python    calendar    fundamentals
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[8]
    Assert Date Arithmetic Correct    ${s}

Days In February During Leap Year
    [Documentation]    February has 29 days in a leap year.
    [Tags]    tier:1    verify:python    calendar    leap
    ${s}=    Set Variable    ${DATE_ARITHMETIC_SCENARIOS}[9]
    Assert Date Arithmetic Correct    ${s}
