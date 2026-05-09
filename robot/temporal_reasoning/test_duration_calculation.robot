*** Settings ***
Documentation     Temporal Duration Calculation Tests
...
...               Asks the LLM to compute the number of complete years elapsed
...               between two precisely dated historical events. The model is
...               instructed to write only the integer answer on the first line.
...
...               The first integer found on that line is compared to the
...               expected ground-truth value, making these Tier 1 / verify:python
...               tests.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    duration    tier:1    verify:python

Test Timeout      2 minutes

*** Test Cases ***

Years From Wright Brothers To Moon Landing
    [Documentation]    1969 − 1903 = 66 years.
    [Tags]    tier:1    verify:python    aviation    space
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[0]
    Assert Duration Correct    ${s}[question]    ${s}[expected_years]

Years From Magna Carta To Declaration Of Independence
    [Documentation]    1776 − 1215 = 561 years.
    [Tags]    tier:1    verify:python    history    law
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[1]
    Assert Duration Correct    ${s}[question]    ${s}[expected_years]

Years From Telephone To iPhone
    [Documentation]    2007 − 1876 = 131 years.
    [Tags]    tier:1    verify:python    technology
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[2]
    Assert Duration Correct    ${s}[question]    ${s}[expected_years]

Years From End Of World War II To Fall Of Berlin Wall
    [Documentation]    1989 − 1945 = 44 years.
    [Tags]    tier:1    verify:python    history    politics
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[3]
    Assert Duration Correct    ${s}[question]    ${s}[expected_years]

Years From Darwin To DNA Double Helix
    [Documentation]    1953 − 1859 = 94 years.
    [Tags]    tier:1    verify:python    biology    science
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[4]
    Assert Duration Correct    ${s}[question]    ${s}[expected_years]

Years From Galileo Telescope To Moon Landing
    [Documentation]    1969 − 1609 = 360 years.
    [Tags]    tier:1    verify:python    astronomy    science
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[5]
    Assert Duration Correct    ${s}[question]    ${s}[expected_years]
