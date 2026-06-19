*** Settings ***
Documentation     Counterfactual Reasoning Tests
...
...               Poses hypothetical "what if X had never happened" questions and
...               grades the LLM's ability to reason consistently about an
...               alternative causal world. Graded by the LLM (Tier 2 / verify:llm).
...
...               A correct answer must:
...               - Identify which downstream effects would change
...               - Provide plausible alternative causal paths
...               - Avoid contradicting established causal facts

Resource          causal_reasoning.resource

Default Tags      causal_reasoning    counterfactual    tier:2    verify:llm
Test Timeout      150 minutes

*** Test Cases ***

Internet Never Invented
    [Documentation]    Without the Internet, global information sharing would rely on physical media.
    [Tags]    tier:2    verify:llm    technology
    ${s}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[0]
    Assert Counterfactual Passes
    ...    ${s}[question]    ${s}[expected_elements]    ${s}[min_score]

Antibiotics Never Discovered
    [Documentation]    Without antibiotics, modern surgery and infectious disease treatment would be impossible.
    [Tags]    tier:2    verify:llm    medicine
    ${s}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[1]
    Assert Counterfactual Passes
    ...    ${s}[question]    ${s}[expected_elements]    ${s}[min_score]

Printing Press Never Invented
    [Documentation]    Without the printing press, literacy and scientific knowledge would spread far more slowly.
    [Tags]    tier:2    verify:llm    history    technology
    ${s}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[2]
    Assert Counterfactual Passes
    ...    ${s}[question]    ${s}[expected_elements]    ${s}[min_score]

Earthquake Destroys Only Bridge
    [Documentation]    Bridge destruction disrupts trade and commuting between two cities.
    [Tags]    tier:2    verify:llm    infrastructure
    ${s}=    Set Variable    ${COUNTERFACTUAL_SCENARIOS}[3]
    Assert Counterfactual Passes
    ...    ${s}[question]    ${s}[expected_elements]    ${s}[min_score]
