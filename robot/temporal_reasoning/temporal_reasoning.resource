*** Settings ***
Documentation     Shared keywords and configuration for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    Temporal
Variables         ${CURDIR}/variables/sequence_scenarios.yaml
Variables         ${CURDIR}/variables/duration_scenarios.yaml
Variables         ${CURDIR}/variables/temporal_word_problems.yaml

*** Keywords ***
Assert Sequence Order Correct
    [Documentation]    Ask the LLM to order events and assert the result matches expected.
    [Arguments]    ${events}    ${expected_order}
    ${result}=    Temporal.Evaluate Sequence Order    ${events}    ${expected_order}
    Log    Extracted: ${result}[extracted_order] | Expected: ${result}[expected_order]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM returned order '${result}[extracted_order]' but expected '${result}[expected_order]'
    RETURN    ${result}

Assert Duration Correct
    [Documentation]    Ask the LLM to calculate a duration and assert correctness.
    [Arguments]    ${question}    ${expected_years}
    ${result}=    Temporal.Evaluate Duration    ${question}    ${expected_years}
    Log    Extracted: ${result}[extracted_years] | Expected: ${result}[expected_years]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM returned '${result}[extracted_years]' years but expected '${result}[expected_years]'
    RETURN    ${result}

Assert Temporal Word Problem Correct
    [Documentation]    Ask the LLM a temporal word problem and assert the first-line answer.
    [Arguments]    ${question}    ${expected_answer}
    ${result}=    Temporal.Evaluate Temporal Word Problem    ${question}    ${expected_answer}
    Log    First line: '${result}[first_line]' | Expected: '${result}[expected_answer]'
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM first-line answer '${result}[first_line]' does not contain '${result}[expected_answer]'
    RETURN    ${result}
