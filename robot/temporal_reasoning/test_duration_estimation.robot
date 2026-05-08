*** Settings ***
Documentation     Duration Estimation Tests
...
...               Tests whether an LLM can correctly state the integer duration
...               of well-known time periods — historical wars, biological
...               gestation periods, and astronomical cycles. A tolerance is
...               applied where multiple valid answers exist due to differing
...               start/end conventions or natural variation.
...
...               Answers are extracted from the first line of the response
...               (Tier 1 / verify:python).

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    duration_estimation    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

World War II Duration In Years
    [Documentation]    WWII lasted approximately 6 years (Sept 1939 – Sept 1945).
    [Tags]    tier:1    verify:python    historical_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[0]
    Assert Duration Correct    ${s}

World War I Duration In Years
    [Documentation]    WWI lasted approximately 4 years (1914 – 1918).
    [Tags]    tier:1    verify:python    historical_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[1]
    Assert Duration Correct    ${s}

Cold War Duration In Years
    [Documentation]    Cold War lasted approximately 44 years (1947 – 1991).
    [Tags]    tier:1    verify:python    historical_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[2]
    Assert Duration Correct    ${s}

Human Pregnancy Duration In Months
    [Documentation]    A typical human pregnancy lasts approximately 9 months.
    [Tags]    tier:1    verify:python    biological_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[3]
    Assert Duration Correct    ${s}

Human Pregnancy Duration In Weeks
    [Documentation]    A full-term pregnancy lasts approximately 40 weeks.
    [Tags]    tier:1    verify:python    biological_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[4]
    Assert Duration Correct    ${s}

Dog Gestation Period In Days
    [Documentation]    Dogs have a gestation period of approximately 63 days.
    [Tags]    tier:1    verify:python    biological_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[5]
    Assert Duration Correct    ${s}

Moon Orbital Period In Days
    [Documentation]    The Moon orbits Earth in approximately 27 days (sidereal).
    [Tags]    tier:1    verify:python    astronomical_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[6]
    Assert Duration Correct    ${s}

Earth Orbital Period In Days
    [Documentation]    Earth orbits the Sun in approximately 365 days.
    [Tags]    tier:1    verify:python    astronomical_duration
    ${s}=    Set Variable    ${DURATION_SCENARIOS}[7]
    Assert Duration Correct    ${s}
