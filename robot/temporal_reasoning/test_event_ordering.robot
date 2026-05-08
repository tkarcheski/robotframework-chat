*** Settings ***
Documentation     Event ordering tests — Tier 1 / verify:python
...
...               Presents 4 labeled events in a non-chronological scramble and
...               asks the LLM to order them correctly.  The answer is extracted
...               deterministically from the first line of the response
...               (e.g. "B, D, A, C"), making these Tier 1 tests with no LLM
...               judge required.
...
...               Events are deliberately labeled out of order so the model
...               cannot answer "A B C D" without reasoning through the dates.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    event_ordering    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Scientific Discoveries Darwin To Turing
    [Documentation]    Order: Darwin (1859), Bell (1876), Einstein (1905), Turing (1936). Expected: B D A C.
    [Tags]    tier:1    verify:python    history    science
    ${s}=    Set Variable    ${EVENT_ORDERING_SCENARIOS}[0]
    Assert Event Order Correct    ${s}[events]    ${s}[expected_order]

World Events Two World Wars To Cold War
    [Documentation]    Order: WW1 (1914), WW2 ends (1945), Moon landing (1969), Berlin Wall (1989). Expected: B D C A.
    [Tags]    tier:1    verify:python    history    world_events
    ${s}=    Set Variable    ${EVENT_ORDERING_SCENARIOS}[1]
    Assert Event Order Correct    ${s}[events]    ${s}[expected_order]

Computing Milestones ENIAC To iPhone
    [Documentation]    Order: ENIAC (1945), email (1971), WWW (1991), iPhone (2007). Expected: B D A C.
    [Tags]    tier:1    verify:python    technology    computing
    ${s}=    Set Variable    ${EVENT_ORDERING_SCENARIOS}[2]
    Assert Event Order Correct    ${s}[events]    ${s}[expected_order]

Space Milestones Gagarin To Voyager
    [Documentation]    Order: Gagarin (1961), Hubble (1990), Mars Sojourner (1997), Voyager 1 (2012). Expected: B C D A.
    [Tags]    tier:1    verify:python    history    space
    ${s}=    Set Variable    ${EVENT_ORDERING_SCENARIOS}[3]
    Assert Event Order Correct    ${s}[events]    ${s}[expected_order]

Internet Companies Google To YouTube
    [Documentation]    Order: Google (1998), Wikipedia (2001), Facebook (2004), YouTube (2005). Expected: B D C A.
    [Tags]    tier:1    verify:python    technology    internet
    ${s}=    Set Variable    ${EVENT_ORDERING_SCENARIOS}[4]
    Assert Event Order Correct    ${s}[events]    ${s}[expected_order]

Medical Breakthroughs Jenner To Watson And Crick
    [Documentation]    Order: Jenner vaccine (1796), Pasteur germ theory (1860s), Fleming penicillin (1928), DNA (1953). Expected: C D A B.
    [Tags]    tier:1    verify:python    history    medicine
    ${s}=    Set Variable    ${EVENT_ORDERING_SCENARIOS}[5]
    Assert Event Order Correct    ${s}[events]    ${s}[expected_order]
