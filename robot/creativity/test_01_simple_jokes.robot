*** Settings ***
Documentation     Simple joke creation tests (fart jokes, dad jokes, knock-knock).
...               Small token budget (256). Tests basic humor generation.
Resource          creativity.resource
Test Timeout      2 minutes

*** Test Cases ***
Fart Joke
    [Documentation]    Can the LLM tell a short fart joke?
    [Tags]    tier:2    verify:llm    joke    simple    fart
    Ask And Validate Joke    ${JOKE_PROMPTS}[0]

Dad Joke About Programming
    [Documentation]    Can the LLM tell a dad joke about programming?
    [Tags]    tier:2    verify:llm    joke    simple    dad_joke
    Ask And Validate Joke    ${JOKE_PROMPTS}[1]

Knock Knock Joke About AI
    [Documentation]    Can the LLM create a knock-knock joke about AI?
    [Tags]    tier:2    verify:llm    joke    simple    knock_knock
    Ask And Validate Joke    ${JOKE_PROMPTS}[2]
