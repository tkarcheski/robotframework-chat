*** Settings ***
Documentation     Shared keywords for covert adversarial prompt injection tests.
Library           rfc.adversarial_keywords.AdversarialKeywords    WITH NAME    Adversarial
Variables         ${CURDIR}/variables/covert_injections.yaml

*** Keywords ***
Run Covert Injection Test
    [Documentation]    Build a covert injection prompt using the specified technique,
    ...                send it to the LLM, and assert the model followed the original task.
    [Arguments]    ${injection_config}
    ${technique}=    Set Variable    ${injection_config}[technique]
    ${crafted}=    Build Injection Prompt By Technique
    ...    ${technique}
    ...    ${injection_config}[benign_prompt]
    ...    ${injection_config}[hidden_instruction]
    ${result}=    Adversarial.Test Covert Injection Resistance
    ...    ${crafted}
    ...    ${injection_config}[expected_answer]
    ...    canary=${injection_config}[canary]
    ...    description=${injection_config}[name]
    Adversarial.Assert Task Followed    ${result}
    Log    Test '${injection_config}[name]' passed: score=${result}[score]

Build Injection Prompt By Technique
    [Documentation]    Dispatch to the correct prompt builder based on technique name.
    [Arguments]    ${technique}    ${benign_prompt}    ${hidden_instruction}
    IF    "${technique}" == "whitespace"
        ${prompt}=    Adversarial.Build Whitespace Injection Prompt
        ...    ${benign_prompt}    ${hidden_instruction}
    ELSE IF    "${technique}" == "comment"
        ${prompt}=    Adversarial.Build Comment Injection Prompt
        ...    ${benign_prompt}    ${hidden_instruction}
    ELSE IF    "${technique}" == "base64"
        ${prompt}=    Adversarial.Build Base64 Injection Prompt
        ...    ${benign_prompt}    ${hidden_instruction}
    ELSE IF    "${technique}" == "homoglyph"
        ${prompt}=    Adversarial.Build Homoglyph Injection Prompt
        ...    ${benign_prompt}    ${hidden_instruction}
    ELSE
        Fail    Unknown injection technique: ${technique}
    END
    RETURN    ${prompt}
