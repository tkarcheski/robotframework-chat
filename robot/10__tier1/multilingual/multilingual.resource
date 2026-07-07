*** Settings ***
Documentation     Common keywords for cross-language instruction-following tests.
...               Reuses the deterministic IFEval constraint checkers to keep
...               grading reproducible across languages.

Resource          ../ifeval/ifeval.resource

*** Keywords ***
Run Multilingual IFEval Test
    [Documentation]    Send a non-English prompt to the LLM and verify a
    ...                deterministic constraint on the response.  Thin wrapper
    ...                around Run IFEval Test so multilingual suites stay
    ...                self-documenting.
    [Arguments]    ${prompt}    ${constraint}    ${expected_value}=${EMPTY}
    ${result}=    Run IFEval Test    ${prompt}    ${constraint}    ${expected_value}
    RETURN    ${result}
