*** Settings ***
Documentation     Shared keywords for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords

*** Variables ***
${TEMPORAL_MIN_SCORE}    0.5

*** Keywords ***
Assert Temporal Exact Match
    [Documentation]    Ask a temporal question and fail if expected string not in response.
    [Arguments]    ${question}    ${expected}
    ${result}=    Run Temporal Exact Match Test    ${question}    ${expected}
    Log    Question: ${question}
    Log    Expected: ${expected}
    Log    Response: ${result}[response]
    Log    Passed: ${result}[passed]
    Should Be True    ${result}[passed]
    ...    Temporal exact match failed — '${expected}' not found in response

Assert Temporal Graded
    [Documentation]    Ask a temporal reasoning question and fail if graded score is below threshold.
    [Arguments]    ${question}    ${expected}    ${min_score}=${TEMPORAL_MIN_SCORE}
    ${result}=    Run Temporal Graded Test    ${question}    ${expected}    min_score=${min_score}
    Log    Question: ${question}
    Log    Expected: ${expected}
    Log    Response: ${result}[response]
    Log    Score: ${result}[score]
    Log    Reason: ${result}[reason]
    Should Be True    ${result}[passed]
    ...    Temporal graded test failed — score ${result}[score] below ${min_score}
