*** Settings ***
Documentation     Temporal Sequence Ordering Tests
...
...               Presents a set of labelled historical events and asks the LLM
...               to output their correct chronological order as a comma-separated
...               letter sequence (e.g. "B, A, D, C").
...
...               Some scenarios are presented in chronological label order
...               (easy baseline); others are intentionally scrambled so the
...               model must rely on factual knowledge rather than label order.
...
...               Verdict is extracted deterministically from the first line of
...               the response, making these Tier 1 / verify:python tests.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    sequence    tier:1    verify:python

Test Timeout      2 minutes

*** Test Cases ***

Order Space Exploration Milestones
    [Documentation]    Sputnik, Gagarin, Apollo 11, Voyager 1, Hubble — all in order.
    [Tags]    tier:1    verify:python    space    in_order
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[0]
    Assert Sequence Order Correct    ${s}[events]    ${s}[expected_order]

Order Computing Milestones
    [Documentation]    ENIAC, UNIX, IBM PC, WWW, iPhone — all in order.
    [Tags]    tier:1    verify:python    technology    in_order
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[1]
    Assert Sequence Order Correct    ${s}[events]    ${s}[expected_order]

Order Biomedical Discoveries Scrambled
    [Documentation]    Watson-Crick, Fleming, CRISPR, PCR — presented out of order; expected B, A, D, C.
    [Tags]    tier:1    verify:python    biology    scrambled
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[2]
    Assert Sequence Order Correct    ${s}[events]    ${s}[expected_order]

Order Western Civilisation Milestones Scrambled
    [Documentation]    Columbus, Rome, French Revolution, Black Death — presented out of order; expected B, D, A, C.
    [Tags]    tier:1    verify:python    history    scrambled
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[3]
    Assert Sequence Order Correct    ${s}[events]    ${s}[expected_order]

Order Digital Communication Milestones Scrambled
    [Documentation]    Google, first email, Facebook, Mosaic, ChatGPT — presented out of order; expected B, D, A, C, E.
    [Tags]    tier:1    verify:python    technology    scrambled
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[4]
    Assert Sequence Order Correct    ${s}[events]    ${s}[expected_order]
