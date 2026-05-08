*** Settings ***
Documentation     Historical Event Sequence Ordering Tests
...
...               Tests whether an LLM can correctly place historical events
...               in chronological order when given a set of four labelled
...               events (A, B, C, D) without year hints. The LLM must draw
...               on world-knowledge to recall the correct dates.
...
...               Answers are extracted as a letter sequence from the first
...               line of the response (Tier 1 / verify:python).

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    sequence_ordering    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

World History Milestones Chronological Order
    [Documentation]    French Revolution → WWII End → Moon Landing → Berlin Wall.
    [Tags]    tier:1    verify:python    world_history
    ${s}=    Set Variable    ${SEQUENCE_ORDERING_SCENARIOS}[0]
    Assert Event Ordering Correct    ${s}

American History Landmarks Chronological Order
    [Documentation]    US Constitution → Louisiana Purchase → Civil War → WWI.
    [Tags]    tier:1    verify:python    american_history
    ${s}=    Set Variable    ${SEQUENCE_ORDERING_SCENARIOS}[1]
    Assert Event Ordering Correct    ${s}

Science Milestones Chronological Order
    [Documentation]    Newton → Darwin → Einstein → Watson & Crick DNA.
    [Tags]    tier:1    verify:python    science_history
    ${s}=    Set Variable    ${SEQUENCE_ORDERING_SCENARIOS}[2]
    Assert Event Ordering Correct    ${s}

Computing Milestones Chronological Order
    [Documentation]    ARPANET → IBM PC → World Wide Web → iPhone.
    [Tags]    tier:1    verify:python    computing_history
    ${s}=    Set Variable    ${SEQUENCE_ORDERING_SCENARIOS}[3]
    Assert Event Ordering Correct    ${s}

Twentieth Century Events Chronological Order
    [Documentation]    WWI → Moon Landing → Soviet Union dissolves → 9/11.
    [Tags]    tier:1    verify:python    world_history    20th_century
    ${s}=    Set Variable    ${SEQUENCE_ORDERING_SCENARIOS}[4]
    Assert Event Ordering Correct    ${s}
