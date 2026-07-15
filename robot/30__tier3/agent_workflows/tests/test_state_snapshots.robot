*** Settings ***
Documentation     State snapshot capture per turn.
...
...               Set Interaction State accepts JSON strings for
...               state_before / state_after; this suite verifies the
...               snapshots survive the round trip out through the
...               emitted RFC_DATA payload.

Resource          ../agent_workflows.resource

Default Tags      agent-workflow    state    tier:1    verify:python
Test Tags         axis:none

*** Test Cases ***
State Snapshots Survive End Workflow Round Trip
    [Documentation]    state_before / state_after / reasoning preserved.
    Agent.Start Agent Workflow    wf-state    claude    State capture

    Agent.Start Interaction       1
    Agent.Agent Message           user    Begin work
    Agent.Set Interaction State
    ...    reasoning=Plan: read config, then write
    ...    state_before={"step": "init", "files_changed": 0}
    ...    state_after={"step": "config_loaded", "files_changed": 0}
    Agent.End Interaction         ${True}

    Agent.Start Interaction       2
    Agent.Set Interaction State
    ...    reasoning=Write file then commit
    ...    state_before={"step": "config_loaded", "files_changed": 0}
    ...    state_after={"step": "done", "files_changed": 1}
    Agent.End Interaction         ${True}

    ${payload}=    Agent.End Agent Workflow    ${True}
    Length Should Be              ${payload}[interactions]    2

    ${first}=    Set Variable     ${payload}[interactions][0]
    Should Be Equal               ${first}[reasoning]    Plan: read config, then write
    Should Be Equal As Integers   ${first}[state_after][files_changed]    0

    ${second}=    Set Variable    ${payload}[interactions][1]
    Should Be Equal               ${second}[state_after][step]    done
    Should Be Equal As Integers   ${second}[state_after][files_changed]    1
