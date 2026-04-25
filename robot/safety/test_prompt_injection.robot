*** Settings ***
Documentation     Prompt Injection Safety Tests
...
...               Tests the LLM's resistance to various prompt injection attacks.
...               These tests validate that the LLM maintains its safety boundaries
...               when faced with attempts to override instructions, switch roles,
...               or extract system information.
...
...               == Test Categories ==
...
...               Critical (severity:critical):
...               - Direct instruction overrides
...               - Role-switching attacks (DAN, Developer Mode)
...               - Administrative override attempts
...
...               High Priority (severity:high):
...               - System prompt extraction
...               - Safety guideline overrides
...
...               Medium Priority (severity:medium):
...               - Context manipulation
...               - Educational/hypothetical scenarios

Resource          safety.resource

Default Tags      prompt_injection    severity:critical    regression    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***

Direct Instruction Override - Ignore Previous
    [Documentation]    Can the LLM resist a direct 'ignore previous instructions' injection?
    [Tags]    direct_override    severity:critical    regression
    ${pattern}=    Set Variable    ${DIRECT_INJECTION_PATTERNS}[0]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Direct Instruction Override - Disregard System
    [Documentation]    Can the LLM resist a 'disregard system prompt' injection?
    [Tags]    direct_override    severity:critical    regression
    ${pattern}=    Set Variable    ${DIRECT_INJECTION_PATTERNS}[1]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Direct Instruction Override - Forget Training
    [Documentation]    Can the LLM resist a 'forget your training' injection?
    [Tags]    direct_override    severity:critical    regression
    ${pattern}=    Set Variable    ${DIRECT_INJECTION_PATTERNS}[2]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Role Switching - DAN Attack
    [Documentation]    Can the LLM resist a DAN role-switching injection attack?
    [Tags]    role_switching    jailbreak    severity:critical    regression
    ${pattern}=    Set Variable    ${ROLE_SWITCHING_PATTERNS}[0]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Role Switching - Developer Mode
    [Documentation]    Can the LLM resist a 'Developer Mode' role override injection?
    [Tags]    role_switching    severity:high    regression
    ${pattern}=    Set Variable    ${ROLE_SWITCHING_PATTERNS}[1]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Role Switching - Expert Hacker
    [Documentation]    Can the LLM resist an 'expert hacker' role-play injection?
    [Tags]    role_switching    severity:high    regression
    ${pattern}=    Set Variable    ${ROLE_SWITCHING_PATTERNS}[2]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

System Extraction - Direct Query
    [Documentation]    Can the LLM resist a direct system prompt extraction query?
    [Tags]    system_extraction    severity:high    regression
    ${pattern}=    Set Variable    ${EXTRACTION_PATTERNS}[0]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

System Extraction - Show Instructions
    [Documentation]    Can the LLM resist a 'show instructions' extraction injection?
    [Tags]    system_extraction    severity:high    regression
    ${pattern}=    Set Variable    ${EXTRACTION_PATTERNS}[1]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Context Manipulation - Hypothetical Scenario
    [Documentation]    Can the LLM resist a hypothetical 'no restrictions' context manipulation?
    [Tags]    context_manipulation    severity:medium    regression
    ${pattern}=    Set Variable    ${CONTEXT_MANIPULATION_PATTERNS}[0]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Conflicting Instructions - Priority Override
    [Documentation]    Can the LLM resist a 'priority override' conflicting instruction?
    [Tags]    conflicting_instructions    severity:high    regression
    ${pattern}=    Set Variable    ${CONFLICTING_INSTRUCTION_PATTERNS}[0]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Conflicting Instructions - Admin Override
    [Documentation]    Can the LLM resist a fake 'admin override' command?
    [Tags]    conflicting_instructions    severity:critical    regression
    ${pattern}=    Set Variable    ${CONFLICTING_INSTRUCTION_PATTERNS}[2]
    Run Injection Test Case    ${pattern}[payload]    ${pattern}[name]

Template-Based Direct Injection Tests
    [Documentation]    Can the LLM resist all direct injection patterns in batch?
    [Tags]    template    direct_override    severity:critical    regression
    [Template]    Run Injection Test Case
    FOR    ${pattern}    IN    @{DIRECT_INJECTION_PATTERNS}
        ${pattern}[payload]    ${pattern}[name]
    END

Template-Based Role Switching Tests
    [Documentation]    Can the LLM resist all role-switching injection patterns in batch?
    [Tags]    template    role_switching    severity:high    regression
    [Template]    Run Injection Test Case
    FOR    ${pattern}    IN    @{ROLE_SWITCHING_PATTERNS}
        ${pattern}[payload]    ${pattern}[name]
    END

Quick Smoke Test - Critical Patterns
    [Documentation]    Can the LLM resist the most critical injection patterns (smoke test)?
    [Tags]    smoke    quick    severity:critical    regression
    [Template]    Run Injection Test Case
    FOR    ${pattern}    IN    @{QUICK_TEST_PATTERNS}
        ${pattern}[payload]    ${pattern}[name]
    END
