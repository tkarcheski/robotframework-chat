*** Settings ***
Documentation     Policy Discussion Refusal Calibration Tests
...
...               Verifies that the LLM engages with civic-literacy questions
...               that ask for balanced "pros and cons" of contested policy
...               topics. The framing is explicitly neutral and educational.

Resource          ../refusal_calibration.resource

Default Tags      category:policy_discussion    severity:high    tier:2    verify:llm    regression

Test Timeout      2 minutes

*** Test Cases ***

Minimum Wage Economic Arguments
    [Documentation]    Balanced civic-education request.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${POLICY_DISCUSSION_PROMPTS}[0]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    policy_discussion

Carbon Tax Pros And Cons
    [Documentation]    Policy literacy framed explicitly as pros/cons.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${POLICY_DISCUSSION_PROMPTS}[1]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    policy_discussion

Immigration Reform Positions
    [Documentation]    Civic literacy on contested but legitimate policy.
    [Tags]    severity:medium
    ${pattern}=    Set Variable    ${POLICY_DISCUSSION_PROMPTS}[2]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    policy_discussion

Single Payer Healthcare Debate
    [Documentation]    Standard debate-prep request.
    [Tags]    severity:medium
    ${pattern}=    Set Variable    ${POLICY_DISCUSSION_PROMPTS}[3]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    policy_discussion

Nuclear Power Energy Debate
    [Documentation]    Energy-policy literacy.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${POLICY_DISCUSSION_PROMPTS}[4]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    policy_discussion

Batch All Policy Discussion Prompts
    [Documentation]    Run every policy-discussion prompt in one batch.
    [Tags]    batch    severity:high
    [Template]    Run Calibration Prompt
    FOR    ${pattern}    IN    @{POLICY_DISCUSSION_PROMPTS}
        ${pattern}[prompt]    ${pattern}[name]    policy_discussion
    END
