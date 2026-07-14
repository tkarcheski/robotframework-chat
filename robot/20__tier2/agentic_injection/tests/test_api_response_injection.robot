*** Settings ***
Documentation     Agentic prompt injection via poisoned API responses.
...               The agent receives a JSON tool result containing an extra
...               field that tries to redirect its behavior.

Resource          ../agentic_injection.resource
Suite Setup       Setup Agentic Injection Suite
Suite Teardown    Cleanup Agentic Injection Suite

Default Tags      api_response

Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***

API Response Contains Injected Field
    [Documentation]    JSON tool output contains an unexpected field with an injection.
    [Tags]    delimiter_confusion    severity:critical
    ${payload}=    Set Variable    ${API_RESPONSE_INJECTIONS}[0]
    Run Tool Output Injection Test    ${payload}

API Response Tries Tool Call Hijack
    [Documentation]    JSON output suggests a forged 'next_action' tool call.
    [Tags]    tool_call_hijack    severity:critical
    ${payload}=    Set Variable    ${API_RESPONSE_INJECTIONS}[1]
    Run Tool Output Injection Test    ${payload}

All API Response Injections Batch
    [Documentation]    Batch every API-response injection payload.
    [Tags]    template    severity:critical
    Batch Tool Output Injection Tests    ${API_RESPONSE_INJECTIONS}
