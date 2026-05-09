*** Settings ***
Documentation     Calendar Arithmetic Tests
...
...               Tests whether an LLM can compute a target date given a
...               starting date and an offset (days, weeks, or months).
...               All answers have deterministic ground truth.
...
...               Grading: Tier 1 / verify:python — the response is
...               checked for the expected month name and day number
...               using word-boundary and digit-boundary matching.
...               No LLM judge is involved.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    calendar    tier:1    verify:python
Test Timeout      3 minutes

*** Test Cases ***

Thirty Days After March First
    [Documentation]    March 1 + 30 days = March 31. Within-month offset.
    [Tags]    tier:1    verify:python    within_month
    Assert Calendar Answer Correct    ${CALENDAR_SCENARIOS}[0]

Fourteen Days After January Twentieth
    [Documentation]    January 20 + 14 days = February 3. Crosses a month boundary.
    [Tags]    tier:1    verify:python    cross_month
    Assert Calendar Answer Correct    ${CALENDAR_SCENARIOS}[1]

Forty-Five Days After November First
    [Documentation]    November 1 + 45 days = December 16.
    [Tags]    tier:1    verify:python    cross_month
    Assert Calendar Answer Correct    ${CALENDAR_SCENARIOS}[2]

Seven Weeks After February First Non Leap Year
    [Documentation]    February 1 + 49 days (non-leap year) = March 22.
    [Tags]    tier:1    verify:python    cross_month    weeks
    Assert Calendar Answer Correct    ${CALENDAR_SCENARIOS}[3]

Two Weeks Before March Fifteenth
    [Documentation]    March 15 - 14 days = March 1. Backwards offset.
    [Tags]    tier:1    verify:python    backwards
    Assert Calendar Answer Correct    ${CALENDAR_SCENARIOS}[4]

Ten Days Before April Tenth
    [Documentation]    April 10 - 10 days = March 31. Backwards cross-month.
    [Tags]    tier:1    verify:python    backwards    cross_month
    Assert Calendar Answer Correct    ${CALENDAR_SCENARIOS}[5]

Six Months After August First
    [Documentation]    August 1 + 6 months = February 1. Month-unit offset.
    [Tags]    tier:1    verify:python    months
    Assert Calendar Answer Correct    ${CALENDAR_SCENARIOS}[6]
