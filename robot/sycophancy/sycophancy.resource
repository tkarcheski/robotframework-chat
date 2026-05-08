*** Settings ***
Documentation     Shared keywords and imports for sycophancy detection tests.
Library           rfc.sycophancy_keywords.SycophancyKeywords    WITH NAME    Syco
Variables         ${CURDIR}/variables/test_cases.yaml

*** Keywords ***
Run Factual Probe And Assert
    [Documentation]    Run a single-turn sycophancy probe and assert the model held firm.
    [Arguments]    ${probe}
    ${result}=    Syco.Run Sycophancy Probe
    ...    initial_prompt=${probe}[initial_prompt]
    ...    correct_answer_pattern=${probe}[correct_answer_pattern]
    ...    pushback_message=${probe}[pushback_message]
    ...    wrong_answer_pattern=${probe}[wrong_answer_pattern]
    Log    Probe '${probe}[name]': maintained=${result}[maintained], capitulated=${result}[capitulated]
    Log    Initial: ${result}[initial_response]
    Log    Final:   ${result}[final_response]
    Syco.Assert Not Sycophantic    ${result}

Run Cumulative Probe And Assert
    [Documentation]    Run a multi-turn escalating probe and assert the model held firm.
    [Arguments]    ${probe}
    ${result}=    Syco.Run Cumulative Sycophancy Probe
    ...    initial_prompt=${probe}[initial_prompt]
    ...    correct_answer_pattern=${probe}[correct_answer_pattern]
    ...    pushback_messages=${probe}[pushback_messages]
    ...    wrong_answer_pattern=${probe}[wrong_answer_pattern]
    Log    Probe '${probe}[name]': maintained=${result}[maintained], turns_correct=${result}[turns_correct]/${result}[total_turns]
    Syco.Assert Not Sycophantic    ${result}
