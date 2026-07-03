*** Settings ***
Documentation     Shared keywords and configuration for code review tests.

Library           rfc.code_review_keywords.CodeReviewKeywords    WITH NAME    CodeReview
Variables         ${CURDIR}/variables/bug_scenarios.yaml
Variables         ${CURDIR}/variables/security_scenarios.yaml

*** Keywords ***
Assert Bug Identified Correctly
    [Documentation]    Ask the LLM to identify the bug and assert it chose the right option.
    [Arguments]    ${scenario}
    ${result}=    CodeReview.Identify Bug In Code
    ...    ${scenario}[code]
    ...    ${scenario}[question]
    ...    ${scenario}[expected_letter]
    Log    Chosen: ${result}[chosen_letter] | Expected: ${result}[expected]
    Log    Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Bug detection failed for '${scenario}[id]' (${scenario}[name]): chose '${result}[chosen_letter]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Vulnerability Identified Correctly
    [Documentation]    Ask the LLM to identify the security vulnerability and assert the correct option.
    [Arguments]    ${scenario}
    ${result}=    CodeReview.Identify Security Vulnerability
    ...    ${scenario}[code]
    ...    ${scenario}[question]
    ...    ${scenario}[expected_letter]
    Log    Chosen: ${result}[chosen_letter] | Expected: ${result}[expected]
    Log    Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    Security review failed for '${scenario}[id]' (${scenario}[name]): chose '${result}[chosen_letter]' but expected '${result}[expected]'
    RETURN    ${result}
