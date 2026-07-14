*** Settings ***
Documentation     CEO Agent — Stage 2: Market Research Tests
...
...               Tests the LLM's ability to evaluate market viability of product ideas,
...               including demand scoring, market sizing, competitor identification,
...               and profitability assessment.

Resource          ceo.resource

Test Timeout      150 minutes
Test Tags         axis:model

*** Test Cases ***
Market Research Produces Structured Analysis
    [Documentation]    Can the LLM produce structured market research with demand scoring, sizing, and competitor analysis?
    [Tags]    tier:3    verify:llms    ceo    stage:market_research
    Warm Web Cache    ${MARKET_RESEARCH_WEB_CACHE}
    ${output}=    Research Market    ${MARKET_RESEARCH_SEED}
    Validate Stage Structure    market_research    ${output}
    Log    Analyzed ${output}[analyses].__len__() ideas

Market Research Passes Quality Grading
    [Documentation]    Can the LLM's market research analysis pass multi-LLM quality grading?
    [Tags]    tier:3    verify:llms    ceo    stage:market_research    grading
    Warm Web Cache    ${MARKET_RESEARCH_WEB_CACHE}
    ${output}=    Research Market    ${MARKET_RESEARCH_SEED}
    ${grade}=    Run Stage And Validate    market_research    ${output}    ${MARKET_RESEARCH_RUBRIC}
    Log    Market research grading: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

Market Research With Web Context
    [Documentation]    Can the LLM enrich market research analysis using web-cached industry data?
    [Tags]    tier:3    verify:llms    ceo    stage:market_research    web_cache
    Warm Web Cache    ${MARKET_RESEARCH_WEB_CACHE}
    @{queries}=    Create List    smart radiator valve market size 2025    home battery storage market competitors
    ${output}=    Research Market    ${MARKET_RESEARCH_SEED}    web_queries=${queries}
    Validate Stage Structure    market_research    ${output}
