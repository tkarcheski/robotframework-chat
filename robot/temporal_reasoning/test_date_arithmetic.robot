*** Settings ***
Documentation     Date arithmetic temporal reasoning tests.
...
...               Tests whether the LLM can add N days to a given date,
...               correctly crossing month and year boundaries.

Resource          temporal_reasoning.resource
Default Tags      temporal_reasoning    date_arithmetic    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Add 30 Days To January 15 2024
    [Documentation]    Jan 15 + 30 days = Feb 14, 2024 (crossing a month boundary).
    [Tags]    date_add    month_boundary
    Ask Date And Pass    ${DATE_ARITHMETIC_SCENARIOS}[0]

Add 7 Days To December 28 2023
    [Documentation]    Dec 28, 2023 + 7 days = Jan 4, 2024 (crossing a year boundary).
    [Tags]    date_add    year_boundary
    Ask Date And Pass    ${DATE_ARITHMETIC_SCENARIOS}[1]
