*** Settings ***
Documentation     Initial Robot Framework test for robotframework-chat MP.
Library           ../../src/rfc/keywords.py    WITH NAME    LLM

*** Variables ***
${QUESTION}      What is 2 + 2?
${EXPECTED}      4

*** Test Cases ***
LLM Can Do Basic Math
    [Documentation]    Test that the LLM correctly answers a simple math question.
    ${answer}=         LLM.Ask LLM    ${QUESTION}
    ${score}    ${reason}=    LLM.Grade Answer    ${QUESTION}    ${EXPECTED}    ${answer}
    Should Be Equal As Integers    ${score}    1
    Log    LLM answer: ${answer} | Reason: ${reason}

LLM Can Do Another Simple Math
    [Documentation]    Test a second math question for regression.
    ${question2}=      Set Variable    What is 5 + 7?
    ${expected2}=      Set Variable    12
    ${answer2}=        LLM.Ask LLM    ${question2}
    ${score2}    ${reason2}=    LLM.Grade Answer    ${question2}    ${expected2}    ${answer2}
    Should Be Equal As Integers    ${score2}    1
    Log    LLM answer: ${answer2} | Reason: ${reason2}
