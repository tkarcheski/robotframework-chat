*** Settings ***
Documentation     Tool failure and retry-after-failure handling.
...
...               Captures a workflow where the first call fails, the
...               agent retries on a subsequent turn, and the second
...               call succeeds.  Asserts that result-level success is
...               not the same as workflow-level success.

Resource          ../agent_workflows.resource

Default Tags      agent-workflow    error-handling    tier:1    verify:python
Test Tags         axis:none

*** Test Cases ***
Workflow Captures Tool Failures And Recovery
    [Documentation]    First API call fails, retry succeeds → workflow OK.
    Agent.Start Agent Workflow    wf-recover    claude    API retry

    Agent.Start Interaction       1
    Agent.Agent Message           assistant     Calling broken endpoint
    ${cid1}=                      Agent.Agent Calls Tool    api    {"endpoint": "/broken"}
    Agent.Agent Receives Tool Result
    ...    ${cid1}    ${False}    output=    error=500 Internal Server Error    execution_time_ms=150
    Agent.Agent Message           assistant     API failed; retrying once
    Agent.End Interaction         ${True}

    Agent.Start Interaction       2
    ${cid2}=                      Agent.Agent Calls Tool    api    {"endpoint": "/broken"}
    Agent.Agent Receives Tool Result    ${cid2}    ${True}    output=Success on retry
    Agent.End Interaction         ${True}

    Run Keyword And Expect Error    *failed: 500*
    ...    Agent.Assert All Tool Calls Succeeded

    Agent.Assert Tool Was Called    api    2

    ${payload}=    Agent.End Agent Workflow    ${True}
    Should Be Equal                ${payload}[status]    completed
    Length Should Be               ${payload}[interactions]    2

Workflow Marks Itself Failed When End Status Is False
    [Documentation]    end_workflow(False, error=...) propagates to status + error.
    Agent.Start Agent Workflow    wf-fail    claude    Hard failure
    Agent.Start Interaction       1
    ${cid}=                       Agent.Agent Calls Tool    api    {}
    Agent.Agent Receives Tool Result    ${cid}    ${False}    error=fatal
    Agent.End Interaction         ${False}    error=could not recover
    ${payload}=    Agent.End Agent Workflow    ${False}    error=workflow aborted
    Should Be Equal                ${payload}[status]    failed
    Should Be Equal                ${payload}[error]     workflow aborted
