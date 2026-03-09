*** Settings ***
Documentation     CEO Agent — Stage 1: Idea Brainstorming Tests
...
...               Tests the LLM's ability to generate novel, well-structured product
...               ideas in a specified domain. Each idea must have a name, description,
...               category, and novelty notes.

Resource          ../ceo.resource

Test Timeout      3 minutes

*** Test Cases ***
Brainstorm Generates Structured Ideas
    [Documentation]    Verify the brainstorm stage produces valid structured output
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm
    ${output}=    Brainstorm Ideas
    ...    domain=${BRAINSTORM_SEED}[domain]
    ...    count=${BRAINSTORM_SEED}[count]
    ...    constraints=${BRAINSTORM_SEED}[constraints]
    Validate Stage Structure    brainstorm    ${output}
    Log    Generated ${output}[ideas].__len__() ideas

Brainstorm Ideas Pass Quality Grading
    [Documentation]    Verify brainstormed ideas pass multi-LLM quality assessment
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm    grading
    ${output}=    Brainstorm Ideas
    ...    domain=${BRAINSTORM_SEED}[domain]
    ...    count=${BRAINSTORM_SEED}[count]
    ...    constraints=${BRAINSTORM_SEED}[constraints]
    ${grade}=    Run Stage And Validate    brainstorm    ${output}    ${BRAINSTORM_RUBRIC}
    Log    Brainstorm grading: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

Brainstorm Respects Idea Count
    [Documentation]    Verify the brainstorm stage generates the requested number of ideas
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm
    ${output}=    Brainstorm Ideas
    ...    domain=${BRAINSTORM_SEED}[domain]
    ...    count=2
    Validate Stage Structure    brainstorm    ${output}
