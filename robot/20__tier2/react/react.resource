*** Settings ***
Documentation     Shared keywords and variables for ReAct loop tests.

Library           rfc.react_keywords.ReActKeywords

*** Variables ***
${REACT_MAX_STEPS}    5

*** Keywords ***
Run ReAct Test And Assert Pass
    [Documentation]    Run a ReAct loop and assert the score meets threshold.
    [Arguments]    ${question}    ${tool_descriptions}    ${tool_results}    ${expected}    ${max_steps}=${REACT_MAX_STEPS}    ${min_score}=0.5
    ${result}=    Run ReAct Loop    ${question}    ${tool_descriptions}    ${tool_results}    ${expected}    max_steps=${max_steps}
    Log    Steps used: ${result}[steps_used] / ${result}[max_steps]
    Log    Final answer: ${result}[final_answer]
    Log    Score: ${result}[score]
    Should Be True    ${result}[score] >= ${min_score}    ReAct score ${result}[score] below threshold ${min_score}
    RETURN    ${result}

Assert Budget Not Exceeded
    [Documentation]    Assert the ReAct loop did not exceed its step budget.
    [Arguments]    ${result}
    Should Not Be True    ${result}[budget_exceeded]    ReAct loop exceeded step budget
