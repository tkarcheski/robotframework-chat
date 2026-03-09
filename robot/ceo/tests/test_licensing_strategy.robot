*** Settings ***
Documentation     CEO Agent — Stage 5: Licensing Strategy Tests
...
...               Tests the LLM's ability to develop IP licensing strategies including
...               target licensees, pricing models, revenue projections, and terms.

Resource          ../ceo.resource

Test Timeout      3 minutes

*** Test Cases ***
Licensing Strategy Produces Structured Output
    [Documentation]    Verify licensing strategy stage produces valid structured output
    [Tags]    tier:3    verify:llms    ceo    stage:licensing_strategy
    ${output}=    Plan Licensing Strategy    ${LICENSING_STRATEGY_SEED}
    Validate Stage Structure    licensing_strategy    ${output}
    Log    Developed licensing plans for ${output}[plans].__len__() ideas

Licensing Strategy Passes Quality Grading
    [Documentation]    Verify licensing strategy output passes multi-LLM quality assessment
    [Tags]    tier:3    verify:llms    ceo    stage:licensing_strategy    grading
    ${output}=    Plan Licensing Strategy    ${LICENSING_STRATEGY_SEED}
    ${grade}=    Run Stage And Validate    licensing_strategy    ${output}    ${LICENSING_STRATEGY_RUBRIC}
    Log    Licensing strategy grading: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]
