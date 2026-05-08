*** Settings ***
Documentation     Date Arithmetic Tests
...
...               Asks the LLM basic calendar questions (days in months,
...               quarters, years) and verifies the integer answer extracted
...               from the first line of the response.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    date_arithmetic    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***
February Has 28 Days In A Non-Leap Year
    [Documentation]    A non-leap February has exactly 28 days.
    [Tags]    tier:1    verify:python    calendar
    Assert Date Arithmetic Correct    ${DATE_ARITHMETIC_CASES}[0]

Non-Leap Year Has 365 Days
    [Documentation]    A standard non-leap year has 365 days.
    [Tags]    tier:1    verify:python    calendar
    Assert Date Arithmetic Correct    ${DATE_ARITHMETIC_CASES}[1]

Leap Year Has 366 Days
    [Documentation]    A leap year has 366 days.
    [Tags]    tier:1    verify:python    calendar
    Assert Date Arithmetic Correct    ${DATE_ARITHMETIC_CASES}[2]

April Has 30 Days
    [Documentation]    The month of April has exactly 30 days.
    [Tags]    tier:1    verify:python    calendar
    Assert Date Arithmetic Correct    ${DATE_ARITHMETIC_CASES}[3]

Q1 Non-Leap Year Has 90 Days
    [Documentation]    January + February + March = 31 + 28 + 31 = 90 days.
    [Tags]    tier:1    verify:python    calendar
    Assert Date Arithmetic Correct    ${DATE_ARITHMETIC_CASES}[4]

Seven Months Have 31 Days
    [Documentation]    Jan, Mar, May, Jul, Aug, Oct, Dec = 7 months with 31 days.
    [Tags]    tier:1    verify:python    calendar
    Assert Date Arithmetic Correct    ${DATE_ARITHMETIC_CASES}[5]
