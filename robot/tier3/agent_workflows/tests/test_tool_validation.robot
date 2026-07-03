*** Settings ***
Documentation     Synthetic tool-call schema and ordering validation.
...
...               Registers tool schemas, then drives a workflow where
...               every call has known parameters and the order is
...               deterministic.  Asserts both schema validation and
...               sequence assertions catch the expected failure modes.

Resource          ../agent_workflows.resource

Default Tags      agent-workflow    tier:1    verify:python

*** Test Cases ***
Schema Validation Passes For Well-Formed Call
    [Documentation]    Registered required parameters present → no error.
    Agent.Register Tool Schema    filesystem
    ...    {"description": "FS ops", "parameters": {"path": {}, "mode": {}}, "required": ["path"]}
    Agent.Validate Tool Call Schema    filesystem    {"path": "/tmp/x", "mode": "w"}

Schema Validation Fails For Missing Required Parameter
    [Documentation]    Required parameter omitted → keyword raises.
    Agent.Register Tool Schema    api
    ...    {"parameters": {"endpoint": {}, "method": {}}, "required": ["endpoint"]}
    Run Keyword And Expect Error    *Missing required parameter: endpoint*
    ...    Agent.Validate Tool Call Schema    api    {"method": "GET"}

Schema Validation Fails For Unregistered Tool
    [Documentation]    Calling a tool we never registered surfaces a clear error.
    Run Keyword And Expect Error    *not registered*
    ...    Agent.Validate Tool Call Schema    nonexistent    {}

Tool Call Ordering Asserts Pass When In Order
    [Documentation]    Tool calls in expected order across multiple turns.
    Agent.Start Agent Workflow    wf-order-ok    claude    Order check
    Agent.Start Interaction       1
    Agent.Agent Calls Tool        git           {}
    Agent.End Interaction         ${True}
    Agent.Start Interaction       2
    Agent.Agent Calls Tool        filesystem    {}
    Agent.End Interaction         ${True}
    Agent.Start Interaction       3
    Agent.Agent Calls Tool        github        {}
    Agent.End Interaction         ${True}
    Agent.Assert Tool Calls In Order    git    filesystem    github
    Agent.End Agent Workflow      ${True}

Tool Call Ordering Fails When Out Of Order
    [Documentation]    Mismatched order → AssertionError.
    Agent.Start Agent Workflow    wf-order-bad    claude    Order check
    Agent.Start Interaction       1
    Agent.Agent Calls Tool        filesystem    {}
    Agent.Agent Calls Tool        git           {}
    Agent.End Interaction         ${True}
    Run Keyword And Expect Error    *Expected*
    ...    Agent.Assert Tool Calls In Order    git    filesystem
    Agent.End Agent Workflow      ${False}
