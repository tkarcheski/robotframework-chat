*** Settings ***
Documentation     Timeline reasoning tests — Tier 2 / verify:llm
...
...               Open-ended scenarios requiring the model to describe a sequence
...               of events in correct chronological order and draw reasonable
...               inferences about the underlying trajectory or cause.
...
...               Responses are graded by a second LLM judge against a set of
...               expected key elements.  A minimum score of 0.4 is required
...               to pass.  These tests catch higher-order temporal reasoning
...               failures: inability to sequence non-trivially ordered events,
...               failure to infer causation from temporal gaps, or omission of
...               critical timeline milestones.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    timeline_reasoning    tier:2    verify:llm
Test Timeout      4 minutes

*** Test Cases ***

Startup Growth Trajectory Product Before Funding
    [Documentation]    Startup founded Jan, beta Apr, 100k users Aug, Series A Nov. Model should identify
    ...                growth-first strategy and note that product traction preceded fundraising.
    [Tags]    tier:2    verify:llm    startup    business
    ${s}=    Set Variable    ${TIMELINE_SCENARIOS}[0]
    Assert Timeline Reasoning Passes
    ...    ${s}[scenario]    ${s}[expected_elements]    ${s}[min_score]

Patient Treatment Switch After Adverse Event
    [Documentation]    Diagnosed Year 1, Treatment A → complication Year 2 → switch to B → stable Year 3.
    ...                Model should note the switch was driven by adverse reaction, not failure of efficacy.
    [Tags]    tier:2    verify:llm    medicine    clinical
    ${s}=    Set Variable    ${TIMELINE_SCENARIOS}[1]
    Assert Timeline Reasoning Passes
    ...    ${s}[scenario]    ${s}[expected_elements]    ${s}[min_score]

Software Project Six Month Delay Due To Bugs
    [Documentation]    Q1 kickoff → Q4 bugs → missed Q1 Year-2 deadline → shipped Q2 Year-2.
    ...                Model should identify late-stage quality issues as the cause of delay.
    [Tags]    tier:2    verify:llm    software    project_management
    ${s}=    Set Variable    ${TIMELINE_SCENARIOS}[2]
    Assert Timeline Reasoning Passes
    ...    ${s}[scenario]    ${s}[expected_elements]    ${s}[min_score]

Roman State Republic Empire Split And Fall
    [Documentation]    509 BCE Republic → 27 BCE Empire → 476 CE Western fall → 1453 CE Byzantine fall.
    ...                Model should quantify the spans and explain the Eastern Empire's greater longevity.
    [Tags]    tier:2    verify:llm    history    long_scale
    ${s}=    Set Variable    ${TIMELINE_SCENARIOS}[3]
    Assert Timeline Reasoning Passes
    ...    ${s}[scenario]    ${s}[expected_elements]    ${s}[min_score]
