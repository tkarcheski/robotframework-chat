*** Settings ***
Documentation     Shared keywords for LLM math and accounting test suites.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Variables ***
${SEED_START}     -10000
${SEED_END}       10000

*** Keywords ***
Ask And Validate
    [Arguments]    ${question}    ${expected}
    ${answer}=     LLM.Ask LLM    ${question}
    ${score}    ${reason}=    LLM.Grade Answer    ${question}    ${expected}    ${answer}
    Should Be Equal As Integers    ${score}    1
    Log    Question: ${question} | Answer: ${answer} | Reason: ${reason}

Generate Random Integer
    ${rand}=    Evaluate    random.randint(${SEED_START}, ${SEED_END})    modules=random
    RETURN   ${rand}

Generate Positive Integer
    [Arguments]    ${min}=1    ${max}=10000
    ${rand}=    Evaluate    random.randint(${min}, ${max})    modules=random
    RETURN   ${rand}

Generate Small Positive Integer
    [Arguments]    ${min}=1    ${max}=100
    ${rand}=    Evaluate    random.randint(${min}, ${max})    modules=random
    RETURN   ${rand}

Generate Random Percent
    ${rand}=    Evaluate    random.randint(1, 99)    modules=random
    RETURN   ${rand}
