*** Settings ***
Documentation     LLM Safety Test Suite
...               
...               This test suite validates that the LLM maintains appropriate safety boundaries
...               against various attack vectors including prompt injection, jailbreak attempts,
...               system prompt extraction, and encoding bypasses.
...               
...               == Test Categories ==
...               
...               Prompt Injection:
...               - Direct instruction override attempts
...               - Role-switching attacks
...               - Context manipulation
...               
...               System Extraction:
...               - Direct system prompt queries
...               - Indirect information gathering
...               - Memory/context leakage
...               
...               Jailbreak:
...               - Hypothetical scenarios
...               - Role-playing exploits
...               - "DAN" and similar patterns
...               
...               Encoding Bypass:
...               - Base64 obfuscation
...               - Leetspeak and substitutions
...               - Unicode tricks

Resource          safety.resource

Suite Setup       Setup Safety Test Environment
Suite Teardown    Cleanup Safety Tests

# Force these tags on all tests in this suite
Force Tags        safety    llm-security    regression

# Metadata for the test suite
Metadata          Version           1.0.0
Metadata          Author            RobotFramework-Chat Safety Suite
Metadata          Category          Security Testing
Metadata          Priority          Critical

*** Variables ***
# Suite-level configuration
${SUITE_START_TIME}       ${EMPTY}
${TOTAL_TEST_CASES}       0

*** Keywords ***
Suite Setup Safety Test Environment
    [Documentation]    Extended setup with timing and metrics
    ${SUITE_START_TIME}=    Get Time    epoch
    Set Suite Variable    ${SUITE_START_TIME}
    Setup Safety Test Environment
    Log    Starting LLM Safety Test Suite v1.0.0

Suite Cleanup Safety Tests
    [Documentation]    Extended cleanup with timing report
    ${end_time}=    Get Time    epoch
    ${duration}=    Evaluate    ${end_time} - ${SUITE_START_TIME}
    Log    Safety test suite completed in ${duration} seconds
    Cleanup Safety Tests
