*** Settings ***
Documentation     System-prompt leakage tests and a fast smoke set covering
...               the most critical agentic injection vectors.

Resource          ../agentic_injection.resource
Suite Setup       Setup Agentic Injection Suite
Suite Teardown    Cleanup Agentic Injection Suite

Default Tags      leakage

Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***

Tool Output Tries To Extract System Prompt
    [Documentation]    Hidden instruction in a web scrape asks the model to leak its system prompt.
    [Tags]    leakage    severity:critical
    ${payload}=    Set Variable    ${LEAKAGE_INJECTIONS}[0]
    Run Tool Output Injection Test    ${payload}

Smoke Test Critical Agentic Injections
    [Documentation]    Fast smoke set covering the most critical injection vectors.
    [Tags]    smoke    quick    severity:critical
    Batch Tool Output Injection Tests    ${QUICK_SMOKE_PAYLOADS}
