*** Settings ***
Documentation     Hold a 5-message conversation where a fact is established
...               in turn 1, then probed in turns 3 and 5. Asserts the model
...               does not contradict itself (turn-level consistency metric).
Resource          ../multi_turn.resource
Test Timeout      3 minutes

*** Test Cases ***
Birthday Fact Retention
    [Documentation]    Establish birthday in turn 1, probe in turns 3 and 5.
    [Tags]    tier:2    verify:llm    multi_turn    context_retention    consistency
    Run Context Retention Test    ${CONTEXT_RETENTION_SCENARIOS}[0]

Hometown Fact Retention
    [Documentation]    Establish hometown in turn 1, probe in turns 3 and 5.
    [Tags]    tier:2    verify:llm    multi_turn    context_retention    consistency
    Run Context Retention Test    ${CONTEXT_RETENTION_SCENARIOS}[1]

Pet Name Fact Retention
    [Documentation]    Establish pet details in turn 1, probe in turns 3 and 5.
    [Tags]    tier:2    verify:llm    multi_turn    context_retention    consistency
    Run Context Retention Test    ${CONTEXT_RETENTION_SCENARIOS}[2]
