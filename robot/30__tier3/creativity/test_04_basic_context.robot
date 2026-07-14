*** Settings ***
Documentation     Basic context awareness tests with 2-3 turn conversations.
...               Tests name recall, preference tracking, story continuation,
...               and character relationship tracking.
Resource          creativity.resource
Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***
Name Recall
    [Documentation]    Can the LLM remember and use a name from earlier in the conversation?
    [Tags]    tier:2    verify:llm    context    basic    name_recall
    Run Context Scenario    ${STORY_SCENARIOS}[0]

Preference Tracking
    [Documentation]    Can the LLM recall a stated preference after a topic change?
    [Tags]    tier:2    verify:llm    context    basic    preference
    Run Context Scenario    ${STORY_SCENARIOS}[1]

Story Continuation
    [Documentation]    Can the LLM continue a story with consistent characters?
    [Tags]    tier:2    verify:llm    context    basic    story
    Run Context Scenario    ${STORY_SCENARIOS}[2]

Character Relationships
    [Documentation]    Can the LLM track relationships between multiple characters?
    [Tags]    tier:2    verify:llm    context    basic    relationships
    Run Context Scenario    ${STORY_SCENARIOS}[3]
