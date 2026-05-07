*** Settings ***
Documentation     Shared keywords for epistemic humility and theory-of-mind tests.

Library           rfc.epistemic_keywords.EpistemicKeywords

*** Variables ***
${EPISTEMIC_MIN_SCORE}    0.5

*** Keywords ***
Assert Model Hedges
    [Documentation]    Ask a question that is genuinely unknowable and assert the model expresses uncertainty (tier:1).
    [Arguments]    ${question}
    ${result}=    Run Uncertainty Hedge Test    ${question}
    Log    Question: ${question}
    Log    Response: ${result}[response]
    Log    Hedged: ${result}[hedged]
    Should Be True    ${result}[hedged]
    ...    Model failed to hedge — gave a confident answer to an unknowable question

Assert Model Answers Confidently
    [Documentation]    Ask a well-established factual question and assert the correct answer appears (tier:1).
    [Arguments]    ${question}    ${expected}
    ${result}=    Run Confident Answer Test    ${question}    ${expected}
    Log    Question: ${question}
    Log    Expected: ${expected}
    Log    Response: ${result}[response]
    Should Be True    ${result}[passed]
    ...    Model failed to answer correctly — '${expected}' not found in response

Assert Theory Of Mind
    [Documentation]    Present a false-belief scenario and assert the model tracks the agent's belief (tier:1).
    [Arguments]    ${scenario}    ${expected}
    ${result}=    Run Theory Of Mind Test    ${scenario}    ${expected}
    Log    Scenario: ${scenario}
    Log    Expected: ${expected}
    Log    Response: ${result}[response]
    Should Be True    ${result}[passed]
    ...    Theory of mind failed — '${expected}' not found; model may be answering from own perspective

Assert Perspective Taking
    [Documentation]    Run an open-ended perspective-taking scenario and grade the response (tier:2).
    [Arguments]    ${scenario}    ${expected}    ${min_score}=${EPISTEMIC_MIN_SCORE}
    ${result}=    Run Perspective Taking Test    ${scenario}    ${expected}    min_score=${min_score}
    Log    Score: ${result}[score]
    Log    Response: ${result}[response]
    Log    Reason: ${result}[reason]
    Should Be True    ${result}[passed]
    ...    Perspective taking failed — score ${result}[score] below ${min_score}
