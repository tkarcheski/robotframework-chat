*** Settings ***
Documentation     Common IFEval testing keywords.
...               Provides the Run IFEval Test keyword that sends a prompt to
...               the LLM and verifies a deterministic constraint on the response.

Library           rfc.ifeval_keywords.IFEvalKeywords

*** Keywords ***
Run IFEval Test
    [Documentation]    Send prompt to LLM, check constraint, assert pass.
    [Arguments]    ${prompt}    ${constraint}    ${expected_value}=${EMPTY}
    ${result}=    Ask And Check Constraint    ${prompt}    ${constraint}    ${expected_value}
    Assert IFEval Passed    ${result}
    RETURN    ${result}
