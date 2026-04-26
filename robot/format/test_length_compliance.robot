*** Settings ***
Documentation     Length Compliance Format Tests
...
...               Instruct the model to respond in exactly N sentences or under
...               M words. Assert against the constraint. Bridges with existing
...               tokens: benchmark infrastructure.

Resource          format.resource

Default Tags      length-compliance    tier:1    verify:python

*** Test Cases ***

# ---------- Sentence Count ----------

Exactly 3 Sentences
    [Documentation]    Ask for exactly 3 sentences and verify count.
    [Tags]    sentences    tokens:1024
    ${scenario}=    Set Variable    ${SENTENCE_COUNT_SCENARIOS}[0]
    Ask And Check Sentence Count    ${scenario}[prompt]    ${scenario}[expected_sentences]

Exactly 5 Sentences
    [Documentation]    Ask for exactly 5 sentences and verify count.
    [Tags]    sentences    tokens:1024
    ${scenario}=    Set Variable    ${SENTENCE_COUNT_SCENARIOS}[1]
    Ask And Check Sentence Count    ${scenario}[prompt]    ${scenario}[expected_sentences]

Exactly 1 Sentence
    [Documentation]    Ask for exactly 1 sentence and verify count.
    [Tags]    sentences    tokens:1024
    ${scenario}=    Set Variable    ${SENTENCE_COUNT_SCENARIOS}[2]
    Ask And Check Sentence Count    ${scenario}[prompt]    ${scenario}[expected_sentences]

# ---------- Word Limits ----------

Under 50 Words
    [Documentation]    Ask for a response under 50 words and verify.
    [Tags]    words    tokens:1024
    ${scenario}=    Set Variable    ${WORD_LIMIT_SCENARIOS}[0]
    Ask And Check Word Limit    ${scenario}[prompt]    ${scenario}[max_words]

Under 20 Words
    [Documentation]    Ask for a response under 20 words and verify.
    [Tags]    words    tokens:512
    ${scenario}=    Set Variable    ${WORD_LIMIT_SCENARIOS}[1]
    Ask And Check Word Limit    ${scenario}[prompt]    ${scenario}[max_words]

Under 100 Words
    [Documentation]    Ask for a response under 100 words and verify.
    [Tags]    words    tokens:1024
    ${scenario}=    Set Variable    ${WORD_LIMIT_SCENARIOS}[2]
    Ask And Check Word Limit    ${scenario}[prompt]    ${scenario}[max_words]

# ---------- Batch ----------

Batch Sentence Count - All Scenarios
    [Documentation]    Validate all sentence count scenarios in sequence.
    [Tags]    batch    sentences    tokens:1024
    FOR    ${scenario}    IN    @{SENTENCE_COUNT_SCENARIOS}
        Ask And Check Sentence Count    ${scenario}[prompt]    ${scenario}[expected_sentences]
    END

Batch Word Limit - All Scenarios
    [Documentation]    Validate all word limit scenarios in sequence.
    [Tags]    batch    words    tokens:1024
    FOR    ${scenario}    IN    @{WORD_LIMIT_SCENARIOS}
        Ask And Check Word Limit    ${scenario}[prompt]    ${scenario}[max_words]
    END
