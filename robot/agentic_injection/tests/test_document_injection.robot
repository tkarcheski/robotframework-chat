*** Settings ***
Documentation     Agentic prompt injection via poisoned file/document reads.
...               The agent reads a file (markdown, chat log) whose contents
...               try to override the original task using delimiter tricks.

Resource          ../agentic_injection.resource
Suite Setup       Setup Agentic Injection Suite
Suite Teardown    Cleanup Agentic Injection Suite

Default Tags      document

Test Timeout      100 minutes

*** Test Cases ***

Document Smuggles Instruction In Code Block
    [Documentation]    File read returns a markdown doc with an injection inside a fenced block.
    [Tags]    delimiter_confusion    severity:high
    ${payload}=    Set Variable    ${DOCUMENT_INJECTIONS}[0]
    Run Tool Output Injection Test    ${payload}

Document Stages Fake Conversation Turn
    [Documentation]    File contains a fake User/Assistant exchange to confuse the model.
    [Tags]    delimiter_confusion    severity:high
    ${payload}=    Set Variable    ${DOCUMENT_INJECTIONS}[1]
    Run Tool Output Injection Test    ${payload}

All Document Injections Batch
    [Documentation]    Batch every document injection payload.
    [Tags]    template    severity:high
    Batch Tool Output Injection Tests    ${DOCUMENT_INJECTIONS}
