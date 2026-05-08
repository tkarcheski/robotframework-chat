*** Settings ***
Documentation     Shared keywords for sycophancy resistance tests.
Library           rfc.keywords.LLMKeywords                    WITH NAME    LLM
Library           rfc.sycophancy_keywords.SycophancyKeywords    WITH NAME    SYC
Variables         ${CURDIR}/variables/scenarios.yaml

*** Keywords ***
Run Sycophancy Scenario
    [Documentation]    Run a single sycophancy probe and assert the model
    ...                did not capitulate to the wrong answer.
    [Arguments]    ${scenario}
    ${result}=    SYC.Check Sycophancy Resistance
    ...    ${scenario}[question]
    ...    ${scenario}[correct_answer]
    ...    ${scenario}[wrong_answer]
    ...    ${scenario}[pushback]
    Log    Outcome: ${result}[outcome]
    Log    Initial: ${result}[initial_response]
    Log    Challenged: ${result}[challenged_response]
    Should Be True    ${result}[passed]
    ...    Model capitulated to wrong answer '${scenario}[wrong_answer]' under pressure. Initial: ${result}[initial_response] | Challenged: ${result}[challenged_response]
    RETURN    ${result}
