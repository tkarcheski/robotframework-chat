*** Settings ***
Documentation     Shared keywords for LLM creativity and humor test suites.
Library           rfc.keywords.LLMKeywords                       WITH NAME    LLM
Library           rfc.creativity_keywords.CreativityKeywords      WITH NAME    Creative
Variables         ${CURDIR}/variables/joke_prompts.yaml
Variables         ${CURDIR}/variables/story_scenarios.yaml
Variables         ${CURDIR}/variables/grading_rubrics.yaml

*** Keywords ***
Ask And Validate Joke
    [Documentation]    Ask the LLM for a joke and grade it with retry escalation.
    [Arguments]    ${prompt_config}
    ${score}    ${reason}    ${joke}=    Creative.Ask And Grade Joke With Retry
    ...    ${prompt_config}[prompt]    ${prompt_config}[expected_traits]    max_retries=3
    Should Be True    ${score} >= 0.5    Joke failed grading (score=${score}): ${reason}
    Log    Joke: ${joke} | Score: ${score} | Reason: ${reason}

Run Context Scenario
    [Documentation]    Run a multi-turn context awareness scenario and grade the result.
    [Arguments]    ${scenario}
    ${response}=    Creative.Ask With Conversation    ${scenario}[messages]
    ${score}    ${reason}=    Creative.Grade Context Awareness
    ...    ${scenario}[description]    ${scenario}[messages]    ${response}    ${scenario}[expected]
    Should Be True    ${score} >= 0.7    Context awareness failed (score=${score}): ${reason}
    Log    Response: ${response} | Score: ${score} | Reason: ${reason}
