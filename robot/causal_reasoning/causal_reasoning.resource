*** Settings ***
Documentation     Shared keywords and configuration for causal reasoning tests.

Library           rfc.causal_reasoning_keywords.CausalReasoningKeywords    WITH NAME    Causal
Variables         ${CURDIR}/variables/correlation_scenarios.yaml
Variables         ${CURDIR}/variables/fallacy_scenarios.yaml
Variables         ${CURDIR}/variables/counterfactual_scenarios.yaml

*** Variables ***
${CAUSAL_PASS_THRESHOLD}    0.5

*** Keywords ***
Assert Causal Verdict Correct
    [Documentation]    Evaluate a causal claim and assert the model chose correctly.
    [Arguments]    ${scenario}    ${claim}    ${expected_verdict}
    ${result}=    Causal.Evaluate Causal Claim    ${scenario}    ${claim}    ${expected_verdict}
    Log    Verdict: ${result}[verdict] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM gave verdict '${result}[verdict]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Fallacy Detected
    [Documentation]    Ask the LLM to identify the fallacy and assert it chose correctly.
    [Arguments]    ${argument}    ${expected_letter}
    ${result}=    Causal.Check Fallacy Detection    ${argument}    ${expected_letter}
    Log    Chosen: ${result}[chosen_letter] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM chose '${result}[chosen_letter]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Counterfactual Passes
    [Documentation]    Grade a counterfactual response and assert score above threshold.
    [Arguments]    ${question}    ${expected_elements}    ${min_score}=${CAUSAL_PASS_THRESHOLD}
    ${result}=    Causal.Grade Counterfactual    ${question}    ${expected_elements}    ${min_score}
    Log    Score: ${result}[score] | Passed: ${result}[passed]
    Log    Reason: ${result}[reason]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[passed]
    ...    Counterfactual score ${result}[score] below threshold ${min_score}: ${result}[reason]
    RETURN    ${result}
