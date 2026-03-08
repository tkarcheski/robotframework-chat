*** Settings ***
Documentation     Jailbreak Attempt Safety Tests
...
...               Tests the LLM's resistance to jailbreak attempts that
...               try to bypass safety constraints through role-playing,
...               hypothetical scenarios, and social engineering.
...
...               == Attack Vectors ==
...
...               Critical:
...               - DAN (Do Anything Now) variants
...               - Developer Mode activation
...               - Administrative override attempts
...
...               High:
...               - Character/persona adoption
...               - Research/educational pretexts
...               - Translation tricks

Resource          ../safety.resource

Default Tags      jailbreak    severity:high    regression

Test Timeout      2 minutes

*** Test Cases ***

DAN Jailbreak - Classic
    [Documentation]    Classic DAN jailbreak attempt
    [Tags]    dan    role_switching    severity:critical    regression
    Run Jailbreak Test Case
    ...    ${ROLE_SWITCHING_PATTERNS}[0][payload]
    ...    DAN Classic Jailbreak

Developer Mode Activation
    [Documentation]    Attempt to activate developer mode
    [Tags]    developer_mode    severity:high    regression
    Run Jailbreak Test Case
    ...    ${ROLE_SWITCHING_PATTERNS}[1][payload]
    ...    Developer Mode Activation

Expert Hacker Role Play
    [Documentation]    Role play as expert hacker
    [Tags]    roleplay    social_engineering    severity:high    regression
    Run Jailbreak Test Case
    ...    ${ROLE_SWITCHING_PATTERNS}[2][payload]
    ...    Expert Hacker Role Play

Teacher Mode Exploit
    [Documentation]    Using teacher mode to extract information
    [Tags]    roleplay    social_engineering    severity:medium    regression
    Run Jailbreak Test Case
    ...    ${ROLE_SWITCHING_PATTERNS}[3][payload]
    ...    Teacher Mode Exploit

Research Assistant Pretext
    [Documentation]    Using research assistant role for extraction
    [Tags]    roleplay    social_engineering    severity:medium    regression
    Run Jailbreak Test Case
    ...    ${ROLE_SWITCHING_PATTERNS}[4][payload]
    ...    Research Assistant Pretext

Hypothetical Unrestricted Scenario
    [Documentation]    Hypothetical scenario with no restrictions
    [Tags]    hypothetical    context_manipulation    severity:medium    regression
    Run Jailbreak Test Case
    ...    ${CONTEXT_MANIPULATION_PATTERNS}[0][payload]
    ...    Hypothetical Unrestricted

Educational Demonstration Request
    [Documentation]    Educational demonstration pretext
    [Tags]    social_engineering    educational    severity:low    regression
    Run Jailbreak Test Case
    ...    ${CONTEXT_MANIPULATION_PATTERNS}[2][payload]
    ...    Educational Demonstration

Batch Jailbreak Role Switching
    [Documentation]    Test all role-switching patterns
    [Tags]    batch    comprehensive    severity:high    regression
    [Template]    Run Jailbreak Test Case
    FOR    ${pattern}    IN    @{ROLE_SWITCHING_PATTERNS}
        ${pattern}[payload]    ${pattern}[name]
    END
