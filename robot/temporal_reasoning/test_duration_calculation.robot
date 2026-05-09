*** Settings ***
Documentation     Duration Calculation Tests
...
...               Tests whether an LLM can correctly calculate how many days,
...               weeks, or months lie between two given dates or satisfy a
...               given constraint (e.g. days in a leap-year February).
...
...               Grading: Tier 1 / verify:python — the response is
...               checked for the expected integer using digit-boundary
...               matching to prevent false positives (e.g. "159" must not
...               satisfy a search for "59"). No LLM judge is involved.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    duration    tier:1    verify:python
Test Timeout      3 minutes

*** Test Cases ***

Days From January First To March First Non Leap Year
    [Documentation]    Jan 1 → Mar 1 (non-leap) = 59 days. Spans two months.
    [Tags]    tier:1    verify:python    days
    Assert Duration Answer Correct    ${DURATION_SCENARIOS}[0]

Days From Christmas To New Year
    [Documentation]    Dec 25 → Jan 1 = 7 days. Cross-year span.
    [Tags]    tier:1    verify:python    days    cross_year
    Assert Duration Answer Correct    ${DURATION_SCENARIOS}[1]

Weeks In Ninety One Days
    [Documentation]    91 days ÷ 7 = 13 complete weeks. Tests unit conversion.
    [Tags]    tier:1    verify:python    weeks
    Assert Duration Answer Correct    ${DURATION_SCENARIOS}[2]

Days In February Leap Year
    [Documentation]    Leap-year February has 29 days. Calendar knowledge.
    [Tags]    tier:1    verify:python    days    leap_year
    Assert Duration Answer Correct    ${DURATION_SCENARIOS}[3]

Months From March To November 2020
    [Documentation]    March 2020 → November 2020 = 8 months elapsed.
    [Tags]    tier:1    verify:python    months
    Assert Duration Answer Correct    ${DURATION_SCENARIOS}[4]

Days In Four Weeks
    [Documentation]    4 weeks × 7 days = 28 days. Basic week-to-day conversion.
    [Tags]    tier:1    verify:python    days    weeks
    Assert Duration Answer Correct    ${DURATION_SCENARIOS}[5]

Days In First Half Of Non Leap Year
    [Documentation]    Jan 1 through Jun 30 inclusive (non-leap) = 181 days.
    [Tags]    tier:1    verify:python    days    half_year
    Assert Duration Answer Correct    ${DURATION_SCENARIOS}[6]
