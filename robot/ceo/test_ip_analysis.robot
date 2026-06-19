*** Settings ***
Documentation     CEO Agent — Stage 3: IP Analysis Tests
...
...               Tests the LLM's ability to analyze intellectual property landscape,
...               identify prior art gaps, and suggest patentable claim angles.

Resource          ceo.resource

Test Timeout      150 minutes

*** Test Cases ***
IP Analysis Produces Structured Findings
    [Documentation]    Can the LLM produce structured IP landscape analysis identifying prior art gaps?
    [Tags]    tier:3    verify:llms    ceo    stage:ip_analysis
    Warm Web Cache    ${IP_ANALYSIS_WEB_CACHE}
    ${output}=    Analyze IP Landscape    ${IP_ANALYSIS_SEED}
    Validate Stage Structure    ip_analysis    ${output}
    Log    Analyzed IP for ${output}[findings].__len__() ideas

IP Analysis Passes Quality Grading
    [Documentation]    Can the LLM's IP landscape analysis pass multi-LLM quality grading?
    [Tags]    tier:3    verify:llms    ceo    stage:ip_analysis    grading
    Warm Web Cache    ${IP_ANALYSIS_WEB_CACHE}
    ${output}=    Analyze IP Landscape    ${IP_ANALYSIS_SEED}
    ${grade}=    Run Stage And Validate    ip_analysis    ${output}    ${IP_ANALYSIS_RUBRIC}
    Log    IP analysis grading: majority=${grade}[majority_score], agreement=${grade}[agreement_ratio]

IP Analysis With Patent Search Context
    [Documentation]    Can the LLM enrich IP analysis using web-cached patent search data?
    [Tags]    tier:3    verify:llms    ceo    stage:ip_analysis    web_cache
    Warm Web Cache    ${IP_ANALYSIS_WEB_CACHE}
    @{queries}=    Create List    smart radiator valve patent prior art    water leak detection ultrasonic patent
    ${output}=    Analyze IP Landscape    ${IP_ANALYSIS_SEED}    web_queries=${queries}
    Validate Stage Structure    ip_analysis    ${output}
