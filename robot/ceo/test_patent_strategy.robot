*** Settings ***
Documentation     CEO Agent — Stage 4: Patent Strategy Tests
...
...               Tests the LLM's ability to develop patent filing strategies including
...               claim types, abstracts, key claims, and filing priorities.

Resource          ../ceo.resource

Test Timeout      3 minutes

*** Test Cases ***
Patent Strategy Produces Structured Output
    [Documentation]    Can the LLM develop structured patent strategies with claim types, abstracts, and filing priorities?
    [Tags]    tier:3    verify:llms    ceo    stage:patent_strategy
    ${output}=    Develop Patent Strategy    ${PATENT_STRATEGY_SEED}
    Validate Stage Structure    patent_strategy    ${output}
    Log    Developed strategies for ${output}[strategies].__len__() ideas

Patent Strategy Passes Quality Grading
    [Documentation]    Can the LLM's patent filing strategies pass multi-LLM quality grading?
    [Tags]    tier:3    verify:llms    ceo    stage:patent_strategy    grading
    ${output}=    Develop Patent Strategy    ${PATENT_STRATEGY_SEED}
    ${grade}=    Run Stage And Validate    patent_strategy    ${output}    ${PATENT_STRATEGY_RUBRIC}
    Log    Patent strategy grading: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]
