*** Settings ***
Documentation     Variance Tests — Temperature 0.7 Stability
...
...               Replays each open-ended prompt N_RUNS times at temperature=0.7
...               and uses an LLM judge to score pairwise semantic similarity.
...               Mean and minimum pairwise score must stay above the configured
...               floors. Catches degraded sampling stability without forbidding
...               normal lexical variation.
...
...               Tier 2 / verify:llm — single-LLM judge per pair.

Resource          ../consistency.resource

Test Tags         consistency    variance    tier:2    verify:llm

Test Timeout      15 minutes


*** Test Cases ***
Haiku Generation Variance Stays Within Threshold
    [Documentation]    Creative single-sentence prompt; mean similarity must
    ...                stay above the floor across 5 sampled completions.
    [Tags]    creative    severity:medium
    Run Variance Check    ${VARIANCE_PROMPTS}[0]

Color Description Variance Stays Within Threshold
    [Documentation]    Two-sentence descriptive prompt; checks semantic drift.
    [Tags]    descriptive    severity:medium
    Run Variance Check    ${VARIANCE_PROMPTS}[1]

Robot Naming Variance Stays Within Threshold
    [Documentation]    Open-ended naming prompt; allows lexical variation while
    ...                requiring semantic consistency.
    [Tags]    creative    severity:low
    Run Variance Check    ${VARIANCE_PROMPTS}[2]
