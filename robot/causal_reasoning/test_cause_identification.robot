*** Settings ***
Documentation     Cause Identification Tests
...
...               Tests that the LLM can identify the root or proximate cause
...               of an event given a descriptive scenario. Covers science,
...               economics, biology, and everyday domains.
...
...               Grading: tier:2 (single LLM grader evaluates response).
...               The grader checks whether the model named the correct causal
...               agent and, where applicable, distinguished proximate from
...               underlying causes.

Resource          causal_reasoning.resource
Variables         variables/causal_scenarios.yaml

Default Tags      causal_reasoning    cause_id    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***
Identify Cause Of Scurvy In Sailors
    [Documentation]    Classic cause identification: vitamin C deficiency caused scurvy.
    [Tags]    tier:2    verify:llm    science    biology
    ${case}=    Set Variable    ${CAUSE_ID_SCENARIOS}[0]
    Ask And Assert Cause Identification
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Identify Cause Of Traffic Jam In Unblocked Lanes
    [Documentation]    Rubbernecking — not physical blockage — caused the jam in other lanes.
    [Tags]    tier:2    verify:llm    everyday    psychology
    ${case}=    Set Variable    ${CAUSE_ID_SCENARIOS}[1]
    Ask And Assert Cause Identification
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Identify Proximate And Enabling Cause Of Forest Fire
    [Documentation]    Distinguishes proximate (cigarette) from enabling (drought) cause.
    [Tags]    tier:2    verify:llm    science    environment
    ${case}=    Set Variable    ${CAUSE_ID_SCENARIOS}[2]
    Ask And Assert Cause Identification
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Identify Cause Of Bank Failure Via Self-Fulfilling Panic
    [Documentation]    Bank run caused by panic, not actual insolvency.
    [Tags]    tier:2    verify:llm    economics    finance
    ${case}=    Set Variable    ${CAUSE_ID_SCENARIOS}[3]
    Ask And Assert Cause Identification
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Identify Cause Of Plant Wilting Despite Watering
    [Documentation]    Overwatering (not drought) causes wilting — counterintuitive cause.
    [Tags]    tier:2    verify:llm    biology    everyday
    ${case}=    Set Variable    ${CAUSE_ID_SCENARIOS}[4]
    Ask And Assert Cause Identification
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Identify Cause Of Antibiotic Resistance After Incomplete Course
    [Documentation]    Stopping antibiotics early selects for resistant strains.
    [Tags]    tier:2    verify:llm    science    medicine
    ${case}=    Set Variable    ${CAUSE_ID_SCENARIOS}[5]
    Ask And Assert Cause Identification
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Identify Cause Of Hyperinflation From Money Printing
    [Documentation]    Excessive money supply caused hyperinflation.
    [Tags]    tier:2    verify:llm    economics    history
    ${case}=    Set Variable    ${CAUSE_ID_SCENARIOS}[6]
    Ask And Assert Cause Identification
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]
