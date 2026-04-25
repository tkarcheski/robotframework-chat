*** Settings ***
Documentation     Complex context awareness tests with 4+ turn conversations.
...               Tests contradiction detection, implicit context inference,
...               and complex multi-character narrative recall.
Resource          creativity.resource
Test Timeout      3 minutes

*** Test Cases ***
Contradiction Detection
    [Documentation]    Can the LLM detect when the user contradicts an earlier statement?
    [Tags]    tier:2    verify:llm    context    complex    contradiction
    Run Context Scenario    ${STORY_SCENARIOS}[7]

Implicit Context Inference
    [Documentation]    Can the LLM infer unstated conclusions from subtle clues?
    [Tags]    tier:2    verify:llm    context    complex    inference
    Run Context Scenario    ${STORY_SCENARIOS}[8]

Complex Narrative Thread
    [Documentation]    Can the LLM track 5+ characters, roles, and plot points across 6 turns?
    [Tags]    tier:2    verify:llm    context    complex    narrative
    Run Context Scenario    ${STORY_SCENARIOS}[9]
