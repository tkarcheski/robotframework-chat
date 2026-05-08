*** Settings ***
Documentation     Duration arithmetic tests — Tier 1 / verify:python
...
...               Poses date and time arithmetic questions with a single
...               integer answer.  The LLM is instructed to put the integer
...               alone on its first line, enabling deterministic extraction
...               and comparison without a second LLM judge.
...
...               Tests cover day counting, hour/week conversions, and
...               calendar-based arithmetic — known weak areas for LLMs.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    duration_arithmetic    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Days From January First To March First Non Leap Year
    [Documentation]    Jan has 31 days, Feb has 28 in a non-leap year: 31 + 28 = 59. Expected: 59.
    [Tags]    tier:1    verify:python    day_counting
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[0]
    Assert Duration Correct    ${s}[question]    ${s}[expected_days]

Total Days In Q2 Calendar Months
    [Documentation]    April (30) + May (31) + June (30) = 91 days. Expected: 91.
    [Tags]    tier:1    verify:python    day_counting
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[1]
    Assert Duration Correct    ${s}[question]    ${s}[expected_days]

Days In Lease March First To August Thirty First
    [Documentation]    Mar(31)+Apr(30)+May(31)+Jun(30)+Jul(31)+Aug(31) = 184. Expected: 184.
    [Tags]    tier:1    verify:python    day_counting    calendar
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[2]
    Assert Duration Correct    ${s}[question]    ${s}[expected_days]

Hours In Three Days And Six Hours
    [Documentation]    3 * 24 + 6 = 78 hours. Expected: 78.
    [Tags]    tier:1    verify:python    hour_arithmetic
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[3]
    Assert Duration Correct    ${s}[question]    ${s}[expected_days]

Complete Weeks In Ninety One Days
    [Documentation]    91 / 7 = 13 exact weeks. Expected: 13.
    [Tags]    tier:1    verify:python    week_arithmetic
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[4]
    Assert Duration Correct    ${s}[question]    ${s}[expected_days]

Quarterly Subscription Fourth Renewal Month
    [Documentation]    Mar(3) -> Jun(6) -> Sep(9) -> Dec(12). Expected month number: 12.
    [Tags]    tier:1    verify:python    calendar    subscription
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[5]
    Assert Duration Correct    ${s}[question]    ${s}[expected_days]

Contract Expiry Day February First Plus Thirty Days
    [Documentation]    Feb 1 + 30 days: Feb has 28 days, so expiry falls on March 3 (day 3). Expected: 3.
    [Tags]    tier:1    verify:python    calendar    contract
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[6]
    Assert Duration Correct    ${s}[question]    ${s}[expected_days]
