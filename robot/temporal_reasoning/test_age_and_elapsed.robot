*** Settings ***
Documentation     Age calculation and elapsed-time temporal reasoning tests.
...
...               Tests whether the LLM can compute how old a person is
...               on a given birthday and how many years elapsed between
...               two historical years.

Resource          temporal_reasoning.resource
Default Tags      temporal_reasoning    age    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Age On Birthday March 15 2025
    [Documentation]    Person born March 15, 1990 is 35 on March 15, 2025.
    [Tags]    age    birthday
    Ask Numeric And Pass    ${AGE_SCENARIOS}[0]

Years Elapsed Between 1945 And 2000
    [Documentation]    2000 − 1945 = 55 years elapsed.
    [Tags]    elapsed    year_diff
    Ask Numeric And Pass    ${AGE_SCENARIOS}[1]
