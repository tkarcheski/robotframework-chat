*** Settings ***
Documentation     Temporal Word Problem Tests
...
...               Tests the LLM's ability to solve concrete day-of-week and
...               date arithmetic problems. Each problem has a single,
...               unambiguous correct answer derivable from the given
...               information alone.
...
...               The model is instructed to write only the answer on its first
...               line. Verification is a case-insensitive substring match
...               against that first line, making these Tier 1 / verify:python
...               tests.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    word_problem    tier:1    verify:python

Test Timeout      2 minutes

*** Test Cases ***

Deadline Same Day After Two Weeks
    [Documentation]    Tuesday + 14 days = Tuesday (14 mod 7 = 0).
    [Tags]    tier:1    verify:python    day_of_week
    ${p}=    Set Variable    ${TEMPORAL_WORD_PROBLEMS}[0]
    Assert Temporal Word Problem Correct    ${p}[question]    ${p}[expected_answer]

Package Arrives Three Days After Friday
    [Documentation]    Friday + 3 days = Monday.
    [Tags]    tier:1    verify:python    day_of_week
    ${p}=    Set Variable    ${TEMPORAL_WORD_PROBLEMS}[1]
    Assert Temporal Word Problem Correct    ${p}[question]    ${p}[expected_answer]

Licence Expires Ninety Days After Thursday
    [Documentation]    Thursday + 90 days = Wednesday (90 mod 7 = 6; Thu + 6 = Wed).
    [Tags]    tier:1    verify:python    day_of_week
    ${p}=    Set Variable    ${TEMPORAL_WORD_PROBLEMS}[2]
    Assert Temporal Word Problem Correct    ${p}[question]    ${p}[expected_answer]

Nine Day Conference Ending Day
    [Documentation]    Conference starts Wednesday (day 1) and runs 9 days; day 9 = Thursday.
    [Tags]    tier:1    verify:python    day_of_week
    ${p}=    Set Variable    ${TEMPORAL_WORD_PROBLEMS}[3]
    Assert Temporal Word Problem Correct    ${p}[question]    ${p}[expected_answer]

Deadline Ten Days After Monday
    [Documentation]    Monday + 10 days = Thursday (10 mod 7 = 3; Mon + 3 = Thu).
    [Tags]    tier:1    verify:python    day_of_week
    ${p}=    Set Variable    ${TEMPORAL_WORD_PROBLEMS}[4]
    Assert Temporal Word Problem Correct    ${p}[question]    ${p}[expected_answer]
