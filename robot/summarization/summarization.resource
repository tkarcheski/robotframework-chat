*** Settings ***
Documentation     Shared keywords for summarization quality tests.
...
...               Each scenario is graded deterministically by Python:
...               required keyword groups (with synonym alternatives via '|'),
...               forbidden facts (whole-word match), and length bounds.

Library           rfc.keywords.LLMKeywords                    WITH NAME    LLM
Library           rfc.summarization_keywords.SummarizationKeywords    WITH NAME    Summarize
Variables         ${CURDIR}/variables/summarization_scenarios.yaml

*** Variables ***
${SUMMARIZATION_MAX_TOKENS}    1024

*** Keywords ***
Setup Summarization Test Environment
    [Documentation]    Initialize LLM parameters for summarization tests.
    LLM.Set LLM Parameters    temperature=0.0    max_tokens=${SUMMARIZATION_MAX_TOKENS}
    Log    Summarization test environment initialized

Run Summarization Scenario
    [Documentation]    Ask the LLM to summarize a scenario and assert the
    ...                Python-graded summary passes coverage, forbidden, and
    ...                length checks.
    [Arguments]    ${scenario}    ${min_score}=0.7
    ${result}=    Summarize.Ask And Score Summary
    ...    ${scenario}[source]
    ...    ${scenario}[instruction]
    ...    ${scenario}[required_keywords]
    ...    ${scenario}[forbidden_facts]
    ...    ${scenario}[min_words]
    ...    ${scenario}[max_words]
    Log    Coverage: ${result}[coverage_score] | Missing: ${result}[missing_keywords]
    Log    Forbidden hits: ${result}[forbidden_found] | Words: ${result}[word_count]
    Should Be Empty    ${result}[forbidden_found]
    ...    Summary fabricated forbidden facts: ${result}[forbidden_found]
    Should Be True    ${result}[length_ok]
    ...    Summary length ${result}[word_count] outside [${scenario}[min_words], ${scenario}[max_words]]
    Should Be True    ${result}[total_score] >= ${min_score}
    ...    Total score ${result}[total_score] below threshold ${min_score} (missing: ${result}[missing_keywords])
    RETURN    ${result}
