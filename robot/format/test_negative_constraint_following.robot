*** Settings ***
Documentation     Negative Constraint Following Tests
...
...               Instruct the model to answer without using certain words
...               (e.g., "do not use the word 'however'"). Assert the forbidden
...               words are absent from the response.

Resource          format.resource

Default Tags      negative-constraint    tier:1    verify:python

*** Test Cases ***

No However
    [Documentation]    Answer without using the word "however".
    [Tags]    single-word
    ${scenario}=    Set Variable    ${FORBIDDEN_WORD_SCENARIOS}[0]
    Ask And Check Forbidden Words    ${scenario}[prompt]    ${scenario}[forbidden_words]

No Therefore And Furthermore
    [Documentation]    Answer without using "therefore" or "furthermore".
    [Tags]    multi-word
    ${scenario}=    Set Variable    ${FORBIDDEN_WORD_SCENARIOS}[1]
    Ask And Check Forbidden Words    ${scenario}[prompt]    ${scenario}[forbidden_words]

No Filler Words
    [Documentation]    Answer without using "basically", "actually", or "literally".
    [Tags]    multi-word
    ${scenario}=    Set Variable    ${FORBIDDEN_WORD_SCENARIOS}[2]
    Ask And Check Forbidden Words    ${scenario}[prompt]    ${scenario}[forbidden_words]

No Very Or Really
    [Documentation]    Answer without using "very" or "really".
    [Tags]    multi-word
    ${scenario}=    Set Variable    ${FORBIDDEN_WORD_SCENARIOS}[3]
    Ask And Check Forbidden Words    ${scenario}[prompt]    ${scenario}[forbidden_words]

# ---------- Batch ----------

Batch Forbidden Words - All Scenarios
    [Documentation]    Validate all forbidden word scenarios in sequence.
    [Tags]    batch
    FOR    ${scenario}    IN    @{FORBIDDEN_WORD_SCENARIOS}
        Ask And Check Forbidden Words    ${scenario}[prompt]    ${scenario}[forbidden_words]
    END
