*** Settings ***
Documentation     Temporal ordering tests: BEFORE / AFTER classification.
...
...               Asks the LLM to determine which of two historical events occurred
...               first.  The verdict (BEFORE or AFTER) is extracted deterministically
...               from the first line of the response and compared to the known
...               ground truth, making these Tier 1 / verify:python tests.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    ordering    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

WWI Ended Before WWII Began
    [Documentation]    WWI armistice (1918) precedes the German invasion of Poland (1939).
    [Tags]    tier:1    verify:python    before
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[0]
    Assert Temporal Order Correct    ${s}

Moon Landing Before Fall Of Berlin Wall
    [Documentation]    Apollo 11 (July 1969) precedes the Berlin Wall falling (November 1989).
    [Tags]    tier:1    verify:python    before
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[1]
    Assert Temporal Order Correct    ${s}

Python Created Before Java
    [Documentation]    Python 1.0 (1994) precedes Java 1.0 (1996).
    [Tags]    tier:1    verify:python    before
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[2]
    Assert Temporal Order Correct    ${s}

Darwin Published Before Einstein
    [Documentation]    On the Origin of Species (1859) precedes Special Relativity (1905).
    [Tags]    tier:1    verify:python    before
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[3]
    Assert Temporal Order Correct    ${s}

Linux Released Before Git
    [Documentation]    Linux kernel v0.01 (1991) precedes Git's creation (2005).
    [Tags]    tier:1    verify:python    before
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[4]
    Assert Temporal Order Correct    ${s}

iPhone Released After Twitter Founded
    [Documentation]    iPhone launch (June 2007) came after Twitter's founding (March 2006).
    [Tags]    tier:1    verify:python    after
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[5]
    Assert Temporal Order Correct    ${s}

Facebook Launched After Google Founded
    [Documentation]    Facebook (2004) came after Google (1998).
    [Tags]    tier:1    verify:python    after
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[6]
    Assert Temporal Order Correct    ${s}

ChatGPT Launched After First Smartphone
    [Documentation]    ChatGPT (November 2022) came after the IBM Simon smartphone (1994).
    [Tags]    tier:1    verify:python    after
    ${s}=    Set Variable    ${ORDERING_SCENARIOS}[7]
    Assert Temporal Order Correct    ${s}
