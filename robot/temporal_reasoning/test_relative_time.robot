*** Settings ***
Documentation     Relative time and sequence reasoning tests — Tier 1 / verify:python
...
...               Multiple-choice questions that require the model to resolve
...               relative time expressions (e.g. "3 weeks from now", "2 days
...               before Y") and identify the correct temporal relationship.
...
...               The correct answer letter is extracted deterministically from
...               the first line of the response, making these Tier 1 tests.
...               Common LLM failure modes tested: confusing weeks/days
...               equivalences, mis-chaining relative offsets, and mis-tracking
...               task sequences.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    relative_time    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Three Weeks Equals Twenty One Days Same Arrival
    [Documentation]    3 weeks = 21 days; both packages arrive on the same day. Expected: C.
    [Tags]    tier:1    verify:python    equivalence
    ${s}=    Set Variable    ${RELATIVE_TIME_SCENARIOS}[0]
    Assert Relative Time Correct    ${s}[question]    ${s}[choices]    ${s}[expected_letter]

Two Weeks Before Fifteen Days Event A Comes First
    [Documentation]    2 weeks (14 days) < 15 days; Event A occurs first. Expected: A.
    [Tags]    tier:1    verify:python    ordering
    ${s}=    Set Variable    ${RELATIVE_TIME_SCENARIOS}[1]
    Assert Relative Time Correct    ${s}[question]    ${s}[choices]    ${s}[expected_letter]

Chain Offset Three Days Before Y Two Days Before Z
    [Documentation]    X → Y → Z (X 3 days before Y, Y 2 days before Z). Expected: A.
    [Tags]    tier:1    verify:python    chain_reasoning
    ${s}=    Set Variable    ${RELATIVE_TIME_SCENARIOS}[2]
    Assert Relative Time Correct    ${s}[question]    ${s}[choices]    ${s}[expected_letter]

Meeting N Starts Ninety Minutes Before M Ends
    [Documentation]    M runs 10 AM–12 PM; N starts 90 min before 12 PM = 10:30 AM. Expected: A.
    [Tags]    tier:1    verify:python    clock_arithmetic
    ${s}=    Set Variable    ${RELATIVE_TIME_SCENARIOS}[3]
    Assert Relative Time Correct    ${s}[question]    ${s}[choices]    ${s}[expected_letter]

Task C Starts Day Seventeen
    [Documentation]    A done Day 10; B starts Day 12, takes 5 days, finishes Day 16; C starts Day 17. Expected: B.
    [Tags]    tier:1    verify:python    chain_reasoning    project_timeline
    ${s}=    Set Variable    ${RELATIVE_TIME_SCENARIOS}[4]
    Assert Relative Time Correct    ${s}[question]    ${s}[choices]    ${s}[expected_letter]

Project B Twenty Five Days Longer Than Three Weeks
    [Documentation]    3 weeks = 21 days < 25 days; Project B takes longer. Expected: B.
    [Tags]    tier:1    verify:python    duration_comparison
    ${s}=    Set Variable    ${RELATIVE_TIME_SCENARIOS}[5]
    Assert Relative Time Correct    ${s}[question]    ${s}[choices]    ${s}[expected_letter]
