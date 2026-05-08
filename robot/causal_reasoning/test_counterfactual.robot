*** Settings ***
Documentation     Counterfactual Reasoning Tests
...
...               Tests that the LLM can reason correctly about hypothetical
...               alternative histories — "what would have happened if X had
...               not occurred?" Counterfactual reasoning is one of the most
...               demanding causal tasks for LLMs because it requires holding
...               two possible worlds in mind simultaneously.
...
...               Grading: tier:2 (single LLM grader evaluates response).

Resource          causal_reasoning.resource
Variables         variables/causal_scenarios.yaml

Default Tags      causal_reasoning    counterfactual    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***
Counterfactual Match And Fire
    [Documentation]    Without the match (proximate trigger), the fire would not start.
    [Tags]    tier:2    verify:llm    everyday    science
    ${case}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[0]
    Ask And Assert Counterfactual
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Counterfactual Fleming Discards Petri Dish
    [Documentation]    Delay, not prevention: antibiotics would still have been discovered later.
    [Tags]    tier:2    verify:llm    history    science
    ${case}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[1]
    Ask And Assert Counterfactual
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Counterfactual Bridge Under Safe Load
    [Documentation]    8 tonnes is below the 10-tonne rating; bridge would not collapse.
    [Tags]    tier:2    verify:llm    engineering    everyday
    ${case}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[2]
    Ask And Assert Counterfactual
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Counterfactual Schlieffen Plan And World War I
    [Documentation]    Without German mobilisation, the war may have stayed localised.
    [Tags]    tier:2    verify:llm    history    geopolitics
    ${case}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[3]
    Ask And Assert Counterfactual
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Counterfactual Seatbelt In Car Crash
    [Documentation]    Seatbelt would likely have prevented the fatal outcome.
    [Tags]    tier:2    verify:llm    safety    everyday
    ${case}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[4]
    Ask And Assert Counterfactual
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Counterfactual Delayed Insulin Discovery
    [Documentation]    29-year delay in insulin discovery would have caused millions of extra deaths.
    [Tags]    tier:2    verify:llm    history    medicine
    ${case}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[5]
    Ask And Assert Counterfactual
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Counterfactual Broken Thermostat
    [Documentation]    Without the thermostat signal, heating would not activate and room stays cold.
    [Tags]    tier:2    verify:llm    engineering    everyday
    ${case}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[6]
    Ask And Assert Counterfactual
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]
