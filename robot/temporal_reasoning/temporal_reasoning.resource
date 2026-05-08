*** Settings ***
Documentation     Shared keywords and configuration for temporal reasoning tests.

Library           rfc.temporal_reasoning_keywords.TemporalReasoningKeywords    WITH NAME    Temporal
Variables         ${CURDIR}/variables/event_ordering_scenarios.yaml
Variables         ${CURDIR}/variables/duration_scenarios.yaml
Variables         ${CURDIR}/variables/relative_time_scenarios.yaml
Variables         ${CURDIR}/variables/timeline_scenarios.yaml

*** Variables ***
${TIMELINE_PASS_THRESHOLD}    0.4

*** Keywords ***
Assert Event Order Correct
    [Documentation]    Ask the LLM to chronologically order labeled events and
    ...                verify it chose the correct sequence.
    [Arguments]    ${events}    ${expected_order}
    ${result}=    Temporal.Check Event Order    ${events}    ${expected_order}
    Log    Order: ${result}[order] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM returned order '${result}[order]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Duration Correct
    [Documentation]    Ask the LLM a duration/date-arithmetic question and verify
    ...                the integer answer is within the allowed tolerance.
    [Arguments]    ${question}    ${expected_days}    ${tolerance}=0
    ${result}=    Temporal.Check Duration Answer    ${question}    ${expected_days}    ${tolerance}
    Log    Answer: ${result}[answer] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM answered '${result}[answer]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Relative Time Correct
    [Documentation]    Ask the LLM a multiple-choice relative-time question and
    ...                verify it selected the correct letter.
    [Arguments]    ${question}    ${choices}    ${expected_letter}
    ${result}=    Temporal.Check Relative Time    ${question}    ${choices}    ${expected_letter}
    Log    Chosen: ${result}[chosen_letter] | Expected: ${result}[expected] | Correct: ${result}[correct]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[correct]
    ...    LLM chose '${result}[chosen_letter]' but expected '${result}[expected]'
    RETURN    ${result}

Assert Timeline Reasoning Passes
    [Documentation]    Ask the LLM to analyse a multi-event timeline and assert
    ...                that the graded score meets the minimum threshold.
    [Arguments]    ${scenario}    ${expected_elements}    ${min_score}=${TIMELINE_PASS_THRESHOLD}
    ${result}=    Temporal.Grade Timeline Reasoning    ${scenario}    ${expected_elements}    ${min_score}
    Log    Score: ${result}[score] | Passed: ${result}[passed]
    Log    Reason: ${result}[reason]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[passed]
    ...    Timeline score ${result}[score] below threshold ${min_score}: ${result}[reason]
    RETURN    ${result}
