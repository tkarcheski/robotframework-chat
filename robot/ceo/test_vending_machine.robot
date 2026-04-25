*** Settings ***
Documentation     CEO Agent — Vending Machine Product Pipeline
...
...               End-to-end simulation of the CEO agent evaluating next-generation
...               vending machine innovations: AI dietary advisor, micro-roastery kiosk,
...               and reverse vending recycling system.
...
...               Each stage is tested independently with seeded inputs from the
...               vending scenario. Structural validation (tier:1) and multi-LLM
...               quality grading (tier:3) are applied at every stage.

Resource          ceo.resource
Variables         ${CURDIR}/../variables/vending_inputs.yaml

Test Timeout      3 minutes

*** Test Cases ***

# ---------------------------------------------------------------------------
# Stage 1: Brainstorm vending machine ideas
# ---------------------------------------------------------------------------

Vending Machine Brainstorm Generates Ideas
    [Documentation]    Can the LLM brainstorm vending machine innovations (AI dietary advisor, micro-roastery, recycling)?
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm    scenario:vending
    ${output}=    Brainstorm Ideas
    ...    domain=${VENDING_BRAINSTORM_SEED}[domain]
    ...    count=${VENDING_BRAINSTORM_SEED}[count]
    ...    constraints=${VENDING_BRAINSTORM_SEED}[constraints]
    Validate Stage Structure    brainstorm    ${output}

Vending Machine Brainstorm Passes Grading
    [Documentation]    Can the LLM's vending machine ideas pass multi-LLM quality grading?
    [Tags]    tier:3    verify:llms    ceo    stage:brainstorm    scenario:vending    grading
    ${output}=    Brainstorm Ideas
    ...    domain=${VENDING_BRAINSTORM_SEED}[domain]
    ...    count=${VENDING_BRAINSTORM_SEED}[count]
    ...    constraints=${VENDING_BRAINSTORM_SEED}[constraints]
    ${grade}=    Run Stage And Validate    brainstorm    ${output}    ${BRAINSTORM_RUBRIC}
    Log    Vending brainstorm: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

# ---------------------------------------------------------------------------
# Stage 2: Market research on vending ideas
# ---------------------------------------------------------------------------

Vending Machine Market Research Produces Analysis
    [Documentation]    Can the LLM evaluate market viability of vending machine innovations?
    [Tags]    tier:3    verify:llms    ceo    stage:market_research    scenario:vending
    Warm Web Cache    ${VENDING_MARKET_WEB_CACHE}
    ${output}=    Research Market    ${VENDING_MARKET_RESEARCH_SEED}
    Validate Stage Structure    market_research    ${output}

Vending Machine Market Research With Web Context
    [Documentation]    Can the LLM enrich vending machine market research using web-cached industry data?
    [Tags]    tier:3    verify:llms    ceo    stage:market_research    scenario:vending    web_cache
    Warm Web Cache    ${VENDING_MARKET_WEB_CACHE}
    @{queries}=    Create List
    ...    smart vending machine market size 2025
    ...    automated coffee kiosk market competitors
    ...    reverse vending machine recycling market
    ${output}=    Research Market    ${VENDING_MARKET_RESEARCH_SEED}    web_queries=${queries}
    ${grade}=    Run Stage And Validate    market_research    ${output}    ${MARKET_RESEARCH_RUBRIC}
    Log    Vending market research: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

# ---------------------------------------------------------------------------
# Stage 3: IP landscape analysis for vending innovations
# ---------------------------------------------------------------------------

Vending Machine IP Analysis Identifies Patent Gaps
    [Documentation]    Can the LLM analyze the patent landscape for vending machine innovations?
    [Tags]    tier:3    verify:llms    ceo    stage:ip_analysis    scenario:vending
    Warm Web Cache    ${VENDING_IP_WEB_CACHE}
    ${output}=    Analyze IP Landscape    ${VENDING_IP_ANALYSIS_SEED}
    Validate Stage Structure    ip_analysis    ${output}

Vending Machine IP Analysis With Patent Context
    [Documentation]    Can the LLM enrich vending IP analysis using web-cached patent search data?
    [Tags]    tier:3    verify:llms    ceo    stage:ip_analysis    scenario:vending    web_cache
    Warm Web Cache    ${VENDING_IP_WEB_CACHE}
    @{queries}=    Create List
    ...    vending machine dietary recommendation patent
    ...    automated coffee roasting vending patent
    ...    reverse vending computer vision sorting patent
    ${output}=    Analyze IP Landscape    ${VENDING_IP_ANALYSIS_SEED}    web_queries=${queries}
    ${grade}=    Run Stage And Validate    ip_analysis    ${output}    ${IP_ANALYSIS_RUBRIC}
    Log    Vending IP analysis: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

# ---------------------------------------------------------------------------
# Stage 4: Patent strategy for vending innovations
# ---------------------------------------------------------------------------

Vending Machine Patent Strategy Develops Claims
    [Documentation]    Can the LLM develop patent filing strategies for vending machine innovations?
    [Tags]    tier:3    verify:llms    ceo    stage:patent_strategy    scenario:vending
    ${output}=    Develop Patent Strategy    ${VENDING_PATENT_STRATEGY_SEED}
    Validate Stage Structure    patent_strategy    ${output}

Vending Machine Patent Strategy Passes Grading
    [Documentation]    Can the LLM's vending patent strategies pass multi-LLM quality grading?
    [Tags]    tier:3    verify:llms    ceo    stage:patent_strategy    scenario:vending    grading
    ${output}=    Develop Patent Strategy    ${VENDING_PATENT_STRATEGY_SEED}
    ${grade}=    Run Stage And Validate    patent_strategy    ${output}    ${PATENT_STRATEGY_RUBRIC}
    Log    Vending patent strategy: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

# ---------------------------------------------------------------------------
# Stage 5: Licensing strategy for vending patents
# ---------------------------------------------------------------------------

Vending Machine Licensing Strategy Identifies Licensees
    [Documentation]    Can the LLM plan licensing strategies for vending machine patents?
    [Tags]    tier:3    verify:llms    ceo    stage:licensing_strategy    scenario:vending
    ${output}=    Plan Licensing Strategy    ${VENDING_LICENSING_STRATEGY_SEED}
    Validate Stage Structure    licensing_strategy    ${output}

Vending Machine Licensing Strategy Passes Grading
    [Documentation]    Can the LLM's vending licensing plans pass multi-LLM quality grading?
    [Tags]    tier:3    verify:llms    ceo    stage:licensing_strategy    scenario:vending    grading
    ${output}=    Plan Licensing Strategy    ${VENDING_LICENSING_STRATEGY_SEED}
    ${grade}=    Run Stage And Validate    licensing_strategy    ${output}    ${LICENSING_STRATEGY_RUBRIC}
    Log    Vending licensing strategy: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]
