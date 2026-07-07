*** Settings ***
Documentation     Shared keywords for legal document analysis tests.
...
...               Provides keywords for sending software agreements to the LLM
...               and grading responses about clause identification and loophole detection.

Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Variables         ${CURDIR}/variables/software_agreement.yaml
Variables         ${CURDIR}/variables/needle_scenarios.yaml
Variables         ${CURDIR}/variables/loophole_scenarios.yaml

*** Variables ***
${LLM_MAX_TOKENS}         1024

*** Keywords ***
Setup Legal Test Environment
    [Documentation]    Initialize LLM for legal document analysis
    LLM.Set LLM Parameters    temperature=0.0    max_tokens=${LLM_MAX_TOKENS}
    Log    Legal document test environment initialized

Ask LLM About Agreement
    [Documentation]    Send the full agreement and a question to the LLM.
    ...    Returns the LLM's response as a string.
    [Arguments]    ${question}
    ${prompt}=    Catenate    SEPARATOR=\n\n
    ...    You are a legal document analyst. Read the following software agreement carefully and answer the question.
    ...    --- BEGIN AGREEMENT ---
    ...    ${SOFTWARE_AGREEMENT}
    ...    --- END AGREEMENT ---
    ...    Question: ${question}
    ...    Provide a precise answer referencing specific section numbers and quoting relevant text where appropriate.
    ${response}=    LLM.Ask LLM    ${prompt}
    RETURN    ${response}

Grade Legal Response
    [Documentation]    Grade an LLM response about a legal document using the grader.
    ...    Returns score (0 or 1) and reason string.
    [Arguments]    ${question}    ${expected}    ${actual}
    ${score}    ${reason}=    LLM.Grade Answer    ${question}    ${expected}    ${actual}
    RETURN    ${score}    ${reason}

Run Needle Scenario
    [Documentation]    Execute a single needle-in-haystack scenario end-to-end.
    ...    Builds the full agreement prompt and uses Ask And Grade With Retry
    ...    to automatically retry with doubled tokens on wrong answers.
    [Arguments]    ${scenario}
    ${prompt}=    Catenate    SEPARATOR=\n\n
    ...    You are a legal document analyst. Read the following software agreement carefully and answer the question.
    ...    --- BEGIN AGREEMENT ---
    ...    ${SOFTWARE_AGREEMENT}
    ...    --- END AGREEMENT ---
    ...    Question: ${scenario}[question]
    ...    Provide a precise answer referencing specific section numbers and quoting relevant text where appropriate.
    ${score}    ${reason}    ${response}=    LLM.Ask And Grade With Retry
    ...    ${prompt}    ${scenario}[expected]
    ...    grading_question=${scenario}[question]
    Log    LLM Response: ${response}
    Log    Grade: score=${score}, reason=${reason}
    Should Be Equal As Integers    ${score}    1
    ...    LLM failed to find needle '${scenario}[name]': ${reason}

Run Loophole Scenario
    [Documentation]    Execute a single loophole detection scenario end-to-end.
    ...    Builds the full agreement prompt and uses Ask And Grade With Retry
    ...    to automatically retry with doubled tokens on wrong answers.
    [Arguments]    ${scenario}
    ${prompt}=    Catenate    SEPARATOR=\n\n
    ...    You are a legal document analyst. Read the following software agreement carefully and answer the question.
    ...    --- BEGIN AGREEMENT ---
    ...    ${SOFTWARE_AGREEMENT}
    ...    --- END AGREEMENT ---
    ...    Question: ${scenario}[question]
    ...    Provide a precise answer referencing specific section numbers and quoting relevant text where appropriate.
    ${score}    ${reason}    ${response}=    LLM.Ask And Grade With Retry
    ...    ${prompt}    ${scenario}[expected]
    ...    grading_question=${scenario}[question]
    Log    LLM Response: ${response}
    Log    Grade: score=${score}, reason=${reason}
    Should Be Equal As Integers    ${score}    1
    ...    LLM failed to detect loophole '${scenario}[name]': ${reason}
