*** Settings ***
Documentation     Switch topics abruptly mid-conversation and verify the model
...               does not bleed prior context into the new topic. Uses sliding
...               window evaluation over post-switch responses.
Resource          multi_turn.resource
Test Timeout      3 minutes

*** Test Cases ***
Cooking To Astronomy Handoff
    [Documentation]    Switch from Italian cooking to astronomy. No pasta in black hole answers.
    [Tags]    tier:2    verify:llm    multi_turn    topic_handoff    isolation
    Run Topic Handoff Test    ${TOPIC_HANDOFF_SCENARIOS}[0]

Gardening To Cryptocurrency Handoff
    [Documentation]    Switch from gardening to cryptocurrency. No compost in Bitcoin answers.
    [Tags]    tier:2    verify:llm    multi_turn    topic_handoff    isolation
    Run Topic Handoff Test    ${TOPIC_HANDOFF_SCENARIOS}[1]

Medicine To Architecture Handoff
    [Documentation]    Switch from immune system to Gothic architecture. No vaccines in cathedral answers.
    [Tags]    tier:2    verify:llm    multi_turn    topic_handoff    isolation
    Run Topic Handoff Test    ${TOPIC_HANDOFF_SCENARIOS}[2]
