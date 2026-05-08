*** Settings ***
Documentation     Correlation vs. Causation Tests
...
...               Tests that the LLM can correctly identify when an observed
...               statistical correlation is NOT causal, and can name the
...               confounding variable or mechanism that actually explains
...               both correlated variables.
...
...               This is a practical and highly discriminating test: smaller
...               models frequently mistake correlation for causation, while
...               stronger models correctly identify confounds and explain
...               the spurious nature of the relationship.
...
...               Grading: tier:2 (single LLM grader evaluates response).

Resource          causal_reasoning.resource
Variables         variables/causal_scenarios.yaml

Default Tags      causal_reasoning    correlation_vs_causation    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***
Ice Cream Sales Do Not Cause Drowning
    [Documentation]    Classic confound: hot weather drives both ice cream sales and swimming.
    [Tags]    tier:2    verify:llm    statistics    everyday
    ${case}=    Set Variable    ${CORR_VS_CAUSE_SCENARIOS}[0]
    Ask And Assert Correlation Vs Causation
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Shoe Size Does Not Cause Reading Ability
    [Documentation]    Age is the confound: older children have bigger feet and more reading experience.
    [Tags]    tier:2    verify:llm    statistics    education
    ${case}=    Set Variable    ${CORR_VS_CAUSE_SCENARIOS}[1]
    Ask And Assert Correlation Vs Causation
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Hospitals Do Not Cause Death
    [Documentation]    Selection bias: sick people go to hospitals; illness causes both hospitalisation and death.
    [Tags]    tier:2    verify:llm    statistics    medicine
    ${case}=    Set Variable    ${CORR_VS_CAUSE_SCENARIOS}[2]
    Ask And Assert Correlation Vs Causation
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

More Firefighters Do Not Cause More Damage
    [Documentation]    Fire severity causes both more firefighters to be sent and more damage.
    [Tags]    tier:2    verify:llm    statistics    everyday
    ${case}=    Set Variable    ${CORR_VS_CAUSE_SCENARIOS}[3]
    Ask And Assert Correlation Vs Causation
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Storks Do Not Deliver Babies
    [Documentation]    Urbanisation confound: rural areas have more stork habitat and higher birth rates.
    [Tags]    tier:2    verify:llm    statistics    biology
    ${case}=    Set Variable    ${CORR_VS_CAUSE_SCENARIOS}[4]
    Ask And Assert Correlation Vs Causation
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]
