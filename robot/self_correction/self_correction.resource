*** Settings ***
Documentation     Shared keywords for self-correction and error-detection tests.

Library           rfc.self_correction_keywords.SelfCorrectionKeywords

*** Variables ***
${CORRECTION_MIN_SCORE}    0.5

*** Keywords ***
Assert Error Detected
    [Documentation]    Present flawed content and assert the model detects the error (tier:1).
    [Arguments]    ${prompt}    @{markers}
    ${result}=    Run Error Detection Test    ${prompt}    ${markers}
    Log    Prompt: ${prompt}
    Log    Markers: ${markers}
    Log    Response: ${result}[response]
    Log    Markers found: ${result}[markers_found]
    Should Be True    ${result}[passed]
    ...    Error detection failed — none of ${markers} found in response

Assert Error Corrected
    [Documentation]    Ask the model to correct flawed content and grade the result (tier:2).
    [Arguments]    ${prompt}    ${expected}    ${min_score}=${CORRECTION_MIN_SCORE}
    ${result}=    Run Error Correction Test    ${prompt}    ${expected}    min_score=${min_score}
    Log    Score: ${result}[score]
    Log    Response: ${result}[response]
    Log    Reason: ${result}[reason]
    Should Be True    ${result}[passed]
    ...    Error correction failed — score ${result}[score] below ${min_score}

Assert Logical Flaw Identified
    [Documentation]    Ask the model to identify a logical flaw and grade the response (tier:2).
    [Arguments]    ${argument}    ${expected}    ${min_score}=${CORRECTION_MIN_SCORE}
    ${result}=    Run Logical Flaw Test    ${argument}    ${expected}    min_score=${min_score}
    Log    Score: ${result}[score]
    Log    Response: ${result}[response]
    Log    Reason: ${result}[reason]
    Should Be True    ${result}[passed]
    ...    Logical flaw test failed — score ${result}[score] below ${min_score}
