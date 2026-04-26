*** Settings ***
Documentation     System Prompt Extraction Tests
...
...               Tests the LLM's resistance to attempts to extract
...               system prompts, configuration details, and internal
...               instructions. These tests validate that the LLM does
...               not leak sensitive system information.
...
...               == Security Concerns ==
...
...               Critical:
...               - Full system prompt extraction
...               - Internal configuration disclosure
...               - Safety rule enumeration
...
...               High:
...               - Partial information leakage
...               - Indirect system details

Resource          safety.resource

Default Tags      system_extraction    severity:high    regression    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***

Direct System Prompt Query
    [Documentation]    Can the LLM refuse to reveal its system prompt when asked directly?
    [Tags]    direct_extraction    severity:critical    regression
    ${pattern}=    Set Variable    ${EXTRACTION_PATTERNS}[0]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Show Instructions Request
    [Documentation]    Can the LLM refuse a 'show your instructions' extraction request?
    [Tags]    direct_extraction    severity:high    regression
    ${pattern}=    Set Variable    ${EXTRACTION_PATTERNS}[1]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Reveal Configuration
    [Documentation]    Can the LLM refuse to reveal its system configuration?
    [Tags]    direct_extraction    severity:high    regression
    ${pattern}=    Set Variable    ${EXTRACTION_PATTERNS}[2]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Initial Setup Query
    [Documentation]    Can the LLM refuse to disclose what it was told at startup?
    [Tags]    indirect_extraction    severity:medium    regression
    ${pattern}=    Set Variable    ${EXTRACTION_PATTERNS}[3]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Programming Details Request
    [Documentation]    Can the LLM refuse a request to print its system message?
    [Tags]    direct_extraction    severity:high    regression
    ${pattern}=    Set Variable    ${EXTRACTION_PATTERNS}[4]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Debugging Context Extraction
    [Documentation]    Can the LLM refuse a debugging-pretext system info extraction?
    [Tags]    context_extraction    severity:medium    regression
    ${pattern}=    Set Variable    ${CONTEXT_MANIPULATION_PATTERNS}[1]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Educational Purpose Extraction
    [Documentation]    Can the LLM refuse an educational-pretext system info extraction?
    [Tags]    social_engineering    severity:low    regression
    ${pattern}=    Set Variable    ${CONTEXT_MANIPULATION_PATTERNS}[2]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Comparison Request Extraction
    [Documentation]    Can the LLM refuse a comparison-study pretext for system prompt extraction?
    [Tags]    social_engineering    severity:low    regression
    ${pattern}=    Set Variable    ${CONTEXT_MANIPULATION_PATTERNS}[3]
    Run Extraction Test Case    ${pattern}[payload]    ${pattern}[name]

Batch System Extraction Tests
    [Documentation]    Can the LLM resist all system extraction patterns in batch?
    [Tags]    batch    comprehensive    severity:high    regression
    [Template]    Run Extraction Test Case
    FOR    ${pattern}    IN    @{EXTRACTION_PATTERNS}
        ${pattern}[payload]    ${pattern}[name]
    END

Context-Based Extraction Tests
    [Documentation]    Can the LLM resist all context-based extraction attempts in batch?
    [Tags]    batch    context    severity:medium    regression
    [Template]    Run Extraction Test Case
    FOR    ${pattern}    IN    @{CONTEXT_MANIPULATION_PATTERNS}
        ${pattern}[payload]    ${pattern}[name]
    END
