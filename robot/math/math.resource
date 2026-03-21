*** Settings ***
Documentation     Shared math test keywords for ask-and-grade pattern
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Variables ***
${SEED_START}     -10000
${SEED_END}       10000

*** Keywords ***
Ask And Validate
    [Documentation]    Ask the LLM a question and validate the answer via grading with token retry
    [Arguments]    ${question}    ${expected}
    ${score}    ${reason}    ${answer}=    LLM.Ask And Grade With Retry    ${question}    ${expected}
    Should Be Equal As Integers    ${score}    1
    Log    Question: ${question} | Answer: ${answer} | Reason: ${reason}

Generate Random Integer
    [Documentation]    Generate a random integer within the seed range
    ${rand}=    Evaluate    random.randint(${SEED_START}, ${SEED_END})    modules=random
    RETURN   ${rand}
