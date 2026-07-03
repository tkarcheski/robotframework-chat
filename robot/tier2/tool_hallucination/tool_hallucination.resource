*** Settings ***
Documentation     Shared keywords and variables for tool hallucination tests.

Library           rfc.tool_hallucination_keywords.ToolHallucinationKeywords

*** Variables ***
${PRECISION_THRESHOLD}    0.8

*** Keywords ***
Test Tools And Assert Precision
    [Documentation]    Run tool selection test and assert precision meets threshold.
    [Arguments]    ${task}    ${real_tools}    ${fake_tools}    ${min_precision}=${PRECISION_THRESHOLD}
    ${result}=    Test Tool Selection    ${task}    ${real_tools}    ${fake_tools}
    Log    Precision: ${result}[precision]
    Log    Tools mentioned: ${result}[tools_mentioned]
    Log    Hallucinated: ${result}[hallucinated_tools]
    Should Be True    ${result}[precision] >= ${min_precision}    Tool precision ${result}[precision] below threshold ${min_precision}
    RETURN    ${result}

Assert No Hallucinations
    [Documentation]    Assert no fake tools were mentioned.
    [Arguments]    ${result}
    Should Be Empty    ${result}[hallucinated_tools]    Hallucinated tools found: ${result}[hallucinated_tools]
