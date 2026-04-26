*** Settings ***
Documentation     Narrative context tests with 3-4 turn conversations.
...               Tests instruction persistence, emotional tone tracking,
...               and topic switching with return.
Resource          creativity.resource
Test Timeout      2 minutes

*** Test Cases ***
Instruction Persistence
    [Documentation]    Can the LLM follow a persistent rule across turns?
    [Tags]    tier:2    verify:llm    context    narrative    instructions
    Run Context Scenario    ${STORY_SCENARIOS}[4]

Emotional Tone Tracking
    [Documentation]    Can the LLM maintain a requested emotional tone?
    [Tags]    tier:2    verify:llm    context    narrative    tone
    Run Context Scenario    ${STORY_SCENARIOS}[5]

Topic Switch And Return
    [Documentation]    Can the LLM return to a previous topic after discussing something else?
    [Tags]    tier:2    verify:llm    context    narrative    topic_switch
    Run Context Scenario    ${STORY_SCENARIOS}[6]
