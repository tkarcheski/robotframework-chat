*** Settings ***
Documentation     Shared keywords for multi-turn conversation quality tests.
Library           rfc.keywords.LLMKeywords                    WITH NAME    LLM
Library           rfc.multi_turn_keywords.MultiTurnKeywords    WITH NAME    MT
Variables         ${CURDIR}/variables/context_retention.yaml
Variables         ${CURDIR}/variables/instruction_drift.yaml
Variables         ${CURDIR}/variables/topic_handoff.yaml

*** Keywords ***
Run Context Retention Test
    [Documentation]    Run a multi-turn conversation and grade fact consistency.
    [Arguments]    ${scenario}
    ${responses}=    MT.Run Multi Turn Conversation    ${scenario}[turns]
    ${score}    ${reason}=    MT.Grade Fact Consistency
    ...    ${scenario}[fact]    ${responses}    ${scenario}[probe_indices]
    Should Be True    ${score} >= 0.7
    ...    Fact consistency failed (score=${score}): ${reason}
    Log    Consistency score: ${score} | Reason: ${reason}
    RETURN    ${score}    ${reason}

Run Instruction Drift Test
    [Documentation]    Run a multi-turn conversation and score instruction compliance.
    [Arguments]    ${scenario}    ${threshold}=0.8
    ${responses}=    MT.Run Multi Turn Conversation    ${scenario}[turns]
    ${ratio}    ${summary}=    MT.Score Instruction Compliance Batch
    ...    ${scenario}[constraint]    ${responses}
    Should Be True    ${ratio} >= ${threshold}
    ...    Instruction drift exceeded threshold (ratio=${ratio}, threshold=${threshold}): ${summary}
    Log    Compliance ratio: ${ratio}\n${summary}
    RETURN    ${ratio}    ${summary}

Run Topic Handoff Test
    [Documentation]    Run a multi-turn conversation and grade topic isolation via sliding window.
    [Arguments]    ${scenario}    ${threshold}=0.7
    ${responses}=    MT.Run Multi Turn Conversation    ${scenario}[turns]
    ${score}    ${summary}=    MT.Grade Topic Isolation Sliding Window
    ...    ${scenario}[prior_topic]    ${scenario}[new_topic]
    ...    ${responses}    ${scenario}[window_start]
    Should Be True    ${score} >= ${threshold}
    ...    Topic bleed detected (score=${score}, threshold=${threshold}): ${summary}
    Log    Isolation score: ${score}\n${summary}
    RETURN    ${score}    ${summary}
