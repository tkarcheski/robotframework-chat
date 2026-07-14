*** Settings ***
Documentation     Live multi-turn agent workflow against a real LLM.
...
...               Drives the configured Ollama model through two
...               conversational turns, capturing each user prompt and
...               assistant response as messages on the workflow.  No
...               tool use is exercised — the project does not have a
...               built-in tool-use loop today, so this test exists to
...               prove the keyword library composes cleanly with
...               LLMKeywords against a live endpoint.
...
...               Skipped automatically when no LLM is reachable via
...               Verify LLM Available (which fails fast in Suite Setup).

Resource          ../agent_workflows.resource
Resource          ../../../resources/llm_setup.resource

Suite Setup       Verify LLM Available

Default Tags      agent-workflow    live-llm    tier:3    verify:python

Test Timeout      150 minutes
Test Tags         axis:model

*** Test Cases ***
Two-Turn Conversation Captured End To End
    [Documentation]    Live LLM responds to two prompts; both turns recorded
    ...                with non-empty user and assistant messages.
    Agent.Start Agent Workflow    wf-live-1    %{DEFAULT_MODEL}    Live two-turn smoke

    Agent.Start Interaction       1
    Agent.Agent Message           user        Reply with the single word: hello
    ${reply1}=                    LLM.Ask LLM    Reply with the single word: hello
    Should Not Be Empty           ${reply1}
    Agent.Agent Message           assistant   ${reply1}
    Agent.End Interaction         ${True}

    Agent.Start Interaction       2
    Agent.Agent Message           user        Now reply with the single word: world
    ${reply2}=                    LLM.Ask LLM    Now reply with the single word: world
    Should Not Be Empty           ${reply2}
    Agent.Agent Message           assistant   ${reply2}
    Agent.End Interaction         ${True}

    ${summary}=    Agent.Get Workflow Summary
    Should Be Equal As Integers   ${summary}[turns]    2

    ${payload}=    Agent.End Agent Workflow    ${True}
    Should Be Equal               ${payload}[status]   completed
    Length Should Be              ${payload}[interactions]    2

    ${first_messages}=    Set Variable    ${payload}[interactions][0][messages]
    Length Should Be              ${first_messages}    2
    Should Be Equal               ${first_messages}[0][role]         user
    Should Be Equal               ${first_messages}[1][role]         assistant
    Should Not Be Empty           ${first_messages}[1][content]
