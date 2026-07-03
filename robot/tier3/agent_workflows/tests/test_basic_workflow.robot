*** Settings ***
Documentation     Synthetic multi-turn agent workflow.
...
...               Drives AgentInteractionTracker through a mocked GitHub
...               issue → PR resolution flow and asserts on the captured
...               workflow summary.  No LLM is invoked; assertions are
...               pure Python via the keyword library.

Resource          ../agent_workflows.resource

Test Tags         agent-workflow    tier:1    verify:python

*** Test Cases ***
Agent Completes Multi-Turn Issue To PR Workflow
    [Documentation]    Three-turn workflow: clone → modify → open PR.
    [Tags]    happy-path
    Agent.Start Agent Workflow    wf-basic-1    claude    Resolve issue \#314

    Agent.Start Interaction       1
    Agent.Agent Message           user        Resolve issue: \#314
    Agent.Agent Message           assistant   I will analyze and create a PR
    ${git_id}=                    Agent.Agent Calls Tool    git    {"cmd": "clone", "url": "https://example.com/repo.git"}
    Agent.Agent Receives Tool Result    ${git_id}    ${True}    output=Cloned repository
    Agent.End Interaction         ${True}

    Agent.Start Interaction       2
    Agent.Agent Message           assistant   Implementing change
    ${fs_id}=                     Agent.Agent Calls Tool    filesystem    {"cmd": "write", "path": "src/feature.py"}
    Agent.Agent Receives Tool Result    ${fs_id}    ${True}    output=File written
    Agent.End Interaction         ${True}

    Agent.Start Interaction       3
    Agent.Agent Message           assistant   Opening PR
    ${pr_id}=                     Agent.Agent Calls Tool    github    {"action": "create_pr", "title": "Resolve \#314"}
    Agent.Agent Receives Tool Result    ${pr_id}    ${True}    output=PR \#999 opened
    Agent.End Interaction         ${True}

    Agent.Assert Tool Was Called          git           1
    Agent.Assert Tool Was Called          filesystem    1
    Agent.Assert Tool Was Called          github        1
    Agent.Assert Tool Calls In Order      git    filesystem    github
    Agent.Assert All Tool Calls Succeeded

    ${summary}=    Agent.Get Workflow Summary
    Should Be Equal As Integers           ${summary}[turns]              3
    Should Be Equal As Integers           ${summary}[tool_calls]         3
    Should Be Equal As Integers           ${summary}[successful_calls]   3
    Should Be Equal                       ${summary}[status]             running

    ${payload}=    Agent.End Agent Workflow    ${True}
    Should Be Equal                       ${payload}[status]             completed
