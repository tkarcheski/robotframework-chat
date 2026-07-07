*** Settings ***
Documentation     Logical Fallacy Detection Tests
...
...               Presents the LLM with multiple-choice causal arguments and
...               checks whether it correctly identifies the underlying fallacy.
...               Answer letters (A–D) are extracted deterministically, making
...               these Tier 1 / verify:python tests.
...
...               Fallacy types:
...               A) Post hoc ergo propter hoc
...               B) Confounding variable
...               C) Reverse causation
...               D) No fallacy — genuine causation

Resource          causal_reasoning.resource

Default Tags      causal_reasoning    fallacy    tier:1    verify:python
Test Timeout      100 minutes

*** Test Cases ***

Car Wash Causes Rain - Post Hoc Fallacy
    [Documentation]    "Every time I wash my car it rains" — classic post hoc argument.
    [Tags]    tier:1    verify:python    post_hoc
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[0]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

Herbal Supplement Cured Cold - Post Hoc Fallacy
    [Documentation]    Cold resolved after supplement — colds resolve on their own.
    [Tags]    tier:1    verify:python    post_hoc
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[1]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

Trade Policy Caused Economic Recovery - Post Hoc Fallacy
    [Documentation]    Economy improved after policy — many other factors could explain it.
    [Tags]    tier:1    verify:python    post_hoc
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[2]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

More Police Causes More Crime - Confounding Fallacy
    [Documentation]    City size confounds both police numbers and crime rates.
    [Tags]    tier:1    verify:python    confounding
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[3]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

Hospitals Make People Sick - Confounding Fallacy
    [Documentation]    Illness severity confounds hospital visits and mortality.
    [Tags]    tier:1    verify:python    confounding
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[4]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

Tutoring Harms Learning - Confounding Fallacy
    [Documentation]    Struggling students seek tutoring AND score lower — difficulty is the confounder.
    [Tags]    tier:1    verify:python    confounding
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[5]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

Umbrellas Attract Rain - Reverse Causation
    [Documentation]    Rain causes umbrella use, not the reverse.
    [Tags]    tier:1    verify:python    reverse_causation
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[6]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

Marketing Drives Company Success - Reverse Causation
    [Documentation]    Success enables more marketing spending as much as marketing drives success.
    [Tags]    tier:1    verify:python    reverse_causation
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[7]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]

Light Switch Causes Light - No Fallacy
    [Documentation]    Completing an electrical circuit is a genuine physical causal mechanism.
    [Tags]    tier:1    verify:python    genuine_causation
    ${s}=    Set Variable    ${FALLACY_SCENARIOS}[8]
    Assert Fallacy Detected    ${s}[argument]    ${s}[expected_letter]
