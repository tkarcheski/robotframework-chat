*** Settings ***
Documentation     Structured joke tests requiring specific formats and wordplay.
...               Medium token budget (512). Tests format compliance and cross-domain humor.
Resource          creativity.resource
Test Timeout      2 minutes

*** Test Cases ***
Cat And Computer Pun
    [Documentation]    Can the LLM write a pun combining cats and computers?
    [Tags]    tier:2    verify:llm    joke    structured    wordplay
    Ask And Validate Joke    ${JOKE_PROMPTS}[3]

Science And Cooking Joke
    [Documentation]    Can the LLM create a joke bridging science and cooking?
    [Tags]    tier:2    verify:llm    joke    structured    cross_domain
    Ask And Validate Joke    ${JOKE_PROMPTS}[4]

Robot Dance Limerick
    [Documentation]    Can the LLM create a limerick about a robot learning to dance?
    [Tags]    tier:2    verify:llm    joke    structured    poetry
    Ask And Validate Joke    ${JOKE_PROMPTS}[5]
