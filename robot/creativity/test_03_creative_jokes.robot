*** Settings ***
Documentation     Complex creative joke tests with multiple constraints.
...               Large token budget (1024-2048) with automatic escalation.
...               Tests constrained wordplay, emotional arcs, and absurd combinations.
Resource          creativity.resource
Test Timeout      150 minutes

*** Test Cases ***
Byte And Bite Wordplay
    [Documentation]    Can the LLM write a joke with a byte/bite punchline?
    [Tags]    tier:2    verify:llm    joke    creative    constrained_wordplay
    Ask And Validate Joke    ${JOKE_PROMPTS}[6]

Sad To Funny Emotional Arc
    [Documentation]    Can the LLM tell a joke that starts sad but ends funny?
    [Tags]    tier:2    verify:llm    joke    creative    emotional_arc
    Ask And Validate Joke    ${JOKE_PROMPTS}[7]

Quantum Physics Dad Joke For Kids
    [Documentation]    Can the LLM create a kid-friendly dad joke about quantum physics?
    [Tags]    tier:2    verify:llm    joke    creative    audience_constrained
    Ask And Validate Joke    ${JOKE_PROMPTS}[8]

Shakespearean Fart Humor
    [Documentation]    Can the LLM combine fart humor with Shakespearean language?
    [Tags]    tier:2    verify:llm    joke    creative    absurd_combination
    Ask And Validate Joke    ${JOKE_PROMPTS}[9]
