*** Settings ***
Documentation     Event Chronology Tests
...
...               Asks the LLM to order pairs of well-known historical events
...               chronologically. The model selects A or B; the answer is
...               verified deterministically by Python (Tier 1 / verify:python).

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    event_chronology    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

WWI Before WWII
    [Documentation]    WWI (1914) predates WWII (1939) — unambiguous ordering.
    [Tags]    tier:1    verify:python    chronology
    ${s}=    Set Variable    ${EVENT_CHRONOLOGY_SCENARIOS}[0]
    Assert Chronological Order Correct    ${s}

American Revolution Before French Revolution
    [Documentation]    American Declaration of Independence (1776) predates the French Revolution (1789).
    [Tags]    tier:1    verify:python    chronology
    ${s}=    Set Variable    ${EVENT_CHRONOLOGY_SCENARIOS}[1]
    Assert Chronological Order Correct    ${s}

Moon Landing Before Berlin Wall Fall
    [Documentation]    First Moon Landing (1969) predates the fall of the Berlin Wall (1989).
    [Tags]    tier:1    verify:python    chronology
    ${s}=    Set Variable    ${EVENT_CHRONOLOGY_SCENARIOS}[2]
    Assert Chronological Order Correct    ${s}

Gutenberg Before Columbus
    [Documentation]    Gutenberg's printing press (circa 1440) predates Columbus reaching the Americas (1492).
    [Tags]    tier:1    verify:python    chronology
    ${s}=    Set Variable    ${EVENT_CHRONOLOGY_SCENARIOS}[3]
    Assert Chronological Order Correct    ${s}

Wright Brothers Before WWI
    [Documentation]    Wright brothers' first flight (1903) predates WWI (1914).
    [Tags]    tier:1    verify:python    chronology
    ${s}=    Set Variable    ${EVENT_CHRONOLOGY_SCENARIOS}[4]
    Assert Chronological Order Correct    ${s}

September Eleven Before Human Genome Project
    [Documentation]    September 11 attacks (2001) predate the Human Genome Project completion (2003).
    [Tags]    tier:1    verify:python    chronology
    ${s}=    Set Variable    ${EVENT_CHRONOLOGY_SCENARIOS}[5]
    Assert Chronological Order Correct    ${s}
