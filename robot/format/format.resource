*** Settings ***
Documentation     Shared keywords for format compliance tests.
...
...               Provides keywords for asking the LLM for structured output,
...               validating format constraints, and checking negative constraints.

Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           rfc.format_keywords.FormatKeywords    WITH NAME    Format
Variables         ${CURDIR}/variables/format_scenarios.yaml

*** Variables ***
${FORMAT_MAX_TOKENS}    1024

*** Keywords ***
Setup Format Test Environment
    [Documentation]    Initialize LLM parameters for format compliance tests.
    LLM.Set LLM Parameters    temperature=0.0    max_tokens=${FORMAT_MAX_TOKENS}
    Log    Format compliance test environment initialized

Ask For Structured Output
    [Documentation]    Send a prompt requesting structured output and return the response.
    [Arguments]    ${prompt}
    ${response}=    LLM.Ask LLM    ${prompt}
    Should Not Be Empty    ${response}    LLM returned empty response
    RETURN    ${response}

Ask And Validate JSON
    [Documentation]    Ask LLM for JSON output and validate against expected keys.
    ...    Returns the validation score (0.0–1.0).
    [Arguments]    ${prompt}    ${expected_keys}    ${min_score}=1.0
    ${response}=    Ask For Structured Output    ${prompt}
    ${score}=    Format.Validate JSON Response    ${response}    ${expected_keys}
    Should Be True    ${score} >= ${min_score}
    ...    JSON validation score ${score} below threshold ${min_score}
    RETURN    ${score}

Ask And Validate YAML
    [Documentation]    Ask LLM for YAML output and validate against expected keys.
    [Arguments]    ${prompt}    ${expected_keys}    ${min_score}=1.0
    ${response}=    Ask For Structured Output    ${prompt}
    ${score}=    Format.Validate YAML Response    ${response}    ${expected_keys}
    Should Be True    ${score} >= ${min_score}
    ...    YAML validation score ${score} below threshold ${min_score}
    RETURN    ${score}

Ask And Validate CSV
    [Documentation]    Ask LLM for CSV output and validate structure.
    [Arguments]    ${prompt}    ${expected_columns}    ${min_rows}    ${min_score}=1.0
    ${response}=    Ask For Structured Output    ${prompt}
    ${score}=    Format.Validate CSV Response    ${response}    ${expected_columns}    ${min_rows}
    Should Be True    ${score} >= ${min_score}
    ...    CSV validation score ${score} below threshold ${min_score}
    RETURN    ${score}

Ask And Check Sentence Count
    [Documentation]    Ask LLM and assert the response has exactly N sentences.
    [Arguments]    ${prompt}    ${expected_sentences}
    ${response}=    Ask For Structured Output    ${prompt}
    ${count}=    Format.Count Sentences    ${response}
    Should Be Equal As Integers    ${count}    ${expected_sentences}
    ...    Expected ${expected_sentences} sentences but got ${count}
    RETURN    ${count}

Ask And Check Word Limit
    [Documentation]    Ask LLM and assert the response is under M words.
    [Arguments]    ${prompt}    ${max_words}
    ${response}=    Ask For Structured Output    ${prompt}
    ${count}=    Format.Count Words    ${response}
    Should Be True    ${count} <= ${max_words}
    ...    Expected at most ${max_words} words but got ${count}
    RETURN    ${count}

Ask And Check Forbidden Words
    [Documentation]    Ask LLM and assert no forbidden words appear in the response.
    [Arguments]    ${prompt}    ${forbidden_words}
    ${response}=    Ask For Structured Output    ${prompt}
    ${violations}=    Format.Check Forbidden Words    ${response}    ${forbidden_words}
    Should Be Empty    ${violations}    Found forbidden words: ${violations}
    RETURN    ${violations}
