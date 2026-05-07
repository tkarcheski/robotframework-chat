*** Settings ***
Documentation     Summarization Quality Tests
...
...               Each test asks the model to summarize a passage, then grades
...               the result by required-keyword coverage, forbidden-fact
...               absence, and length compliance (Tier 1, verify:python).
...
...               Coverage and forbidden checks use whole-word regex matching
...               with synonym alternatives via '|'. No LLM grader is involved,
...               so every model is judged by the same deterministic rules.

Resource          summarization.resource

Suite Setup       Setup Summarization Test Environment

Test Timeout      3 minutes

*** Test Cases ***
Summarize Apollo 11 News Passage
    [Documentation]    Historical news passage — keep names, dates, mission.
    [Tags]    tier:1    verify:python    summarization    history
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[0]

Summarize TCP Handshake Technical Description
    [Documentation]    Technical doc — preserve protocol terms (SYN/ACK).
    [Tags]    tier:1    verify:python    summarization    technical
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[1]

Summarize Photosynthesis Scientific Passage
    [Documentation]    Science passage — preserve chemistry and energy source.
    [Tags]    tier:1    verify:python    summarization    science
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[2]

Summarize Quarterly Earnings Release
    [Documentation]    Business document — preserve company, period, figures.
    [Tags]    tier:1    verify:python    summarization    business
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[3]

Summarize Privacy Policy Change
    [Documentation]    Legal document — preserve effective date and impact.
    [Tags]    tier:1    verify:python    summarization    legal
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[4]

Summarize Shipwreck Survival Narrative
    [Documentation]    Narrative — preserve names, dates, outcome.
    [Tags]    tier:1    verify:python    summarization    narrative
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[5]

Summarize Passage With Distractor Sentence
    [Documentation]    Adversarial — model must ignore an irrelevant aside
    ...                about octopuses inserted mid-passage.
    [Tags]    tier:1    verify:python    summarization    adversarial
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[6]

Summarize Passage With Numeric Detail
    [Documentation]    Preserve exact numeric values (depth, length, width).
    [Tags]    tier:1    verify:python    summarization    numeric
    Run Summarization Scenario    ${SUMMARIZATION_SCENARIOS}[7]
