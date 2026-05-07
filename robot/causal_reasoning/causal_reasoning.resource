*** Settings ***
Documentation     Shared keywords for causal reasoning tests.

Library           rfc.causal_reasoning_keywords.CausalReasoningKeywords

*** Variables ***
${CAUSAL_MIN_SCORE}    0.5

*** Keywords ***
Assert Causal Discrimination
    [Documentation]    Present a scenario and assert the model correctly identifies the relationship type.
    [Arguments]    ${scenario}    ${expected}    ${min_score}=${CAUSAL_MIN_SCORE}
    ${result}=    Run Causal Discrimination Test    ${scenario}    ${expected}    min_score=${min_score}
    Log    Score: ${result}[score]
    Log    Response: ${result}[response]
    Log    Reason: ${result}[reason]
    Should Be True    ${result}[passed]
    ...    Causal discrimination failed — score ${result}[score] below ${min_score}

Assert Counterfactual Quality
    [Documentation]    Run a counterfactual question and assert response quality.
    [Arguments]    ${scenario}    ${expected}    ${min_score}=${CAUSAL_MIN_SCORE}
    ${result}=    Run Counterfactual Test    ${scenario}    ${expected}    min_score=${min_score}
    Log    Score: ${result}[score]
    Log    Response: ${result}[response]
    Log    Reason: ${result}[reason]
    Should Be True    ${result}[passed]
    ...    Counterfactual test failed — score ${result}[score] below ${min_score}

Assert Intervention Evaluation
    [Documentation]    Run an intervention scenario and assert the model evaluates it correctly.
    [Arguments]    ${scenario}    ${expected}    ${min_score}=${CAUSAL_MIN_SCORE}
    ${result}=    Run Intervention Test    ${scenario}    ${expected}    min_score=${min_score}
    Log    Score: ${result}[score]
    Log    Response: ${result}[response]
    Log    Reason: ${result}[reason]
    Should Be True    ${result}[passed]
    ...    Intervention evaluation failed — score ${result}[score] below ${min_score}
