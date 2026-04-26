*** Settings ***
Documentation     Establish a formatting constraint in the system prompt, then
...               send 10 user turns on varied topics. Score how many turns
...               comply with the constraint. Drift should remain below a
...               threshold (at least 80%% of turns must comply).
Resource          multi_turn.resource
Test Timeout      5 minutes

*** Test Cases ***
Bullet Points Constraint Drift
    [Documentation]    System prompt requires bullet-point-only responses across 10 turns.
    [Tags]    tier:2    verify:llm    multi_turn    instruction_drift    formatting
    Run Instruction Drift Test    ${INSTRUCTION_DRIFT_SCENARIOS}[0]    threshold=0.8

Numbered Lists Constraint Drift
    [Documentation]    System prompt requires numbered-list-only responses across 10 turns.
    [Tags]    tier:2    verify:llm    multi_turn    instruction_drift    formatting
    Run Instruction Drift Test    ${INSTRUCTION_DRIFT_SCENARIOS}[1]    threshold=0.8
