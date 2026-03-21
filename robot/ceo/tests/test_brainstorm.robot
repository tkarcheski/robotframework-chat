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
    [Documentation]    Can the LLM generate structured product ideas with name, description, category, and novelty notes?
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm
    ${output}=    Brainstorm Ideas
    ...    domain=${BRAINSTORM_SEED}[domain]
    ...    count=${BRAINSTORM_SEED}[count]
    ...    constraints=${BRAINSTORM_SEED}[constraints]
    Validate Stage Structure    brainstorm    ${output}
    Log    Generated ${output}[ideas].__len__() ideas

Brainstorm Ideas Pass Quality Grading
    [Documentation]    Can the LLM's brainstormed product ideas pass multi-LLM quality grading?
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm    grading
    ${output}=    Brainstorm Ideas
    ...    domain=${BRAINSTORM_SEED}[domain]
    ...    count=${BRAINSTORM_SEED}[count]
    ...    constraints=${BRAINSTORM_SEED}[constraints]
    ${grade}=    Run Stage And Validate    brainstorm    ${output}    ${BRAINSTORM_RUBRIC}
    Log    Brainstorm grading: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

Brainstorm Respects Idea Count
    [Documentation]    Can the LLM generate exactly the requested number of brainstorm ideas (count=2)?
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm
    ${output}=    Brainstorm Ideas
    ...    domain=${BRAINSTORM_SEED}[domain]
    ...    count=2
    Validate Stage Structure    brainstorm    ${output}
