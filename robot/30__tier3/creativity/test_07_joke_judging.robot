*** Settings ***
Documentation     Multi-LLM joke judging tests using consensus grading.
...               Generates jokes and grades them with a panel of 3+
...               judge models distinct from the generation model
...               (CREATIVITY_GRADER_MODELS) to avoid self-grading bias
...               (issue #260). Tests skip if the env var is unset.
...               Tests a simple, medium, and complex joke for quality.
Resource          creativity.resource
Test Timeout      250 minutes
Test Tags         axis:model

*** Test Cases ***
Judge Simple Fart Joke
    [Documentation]    Generate and strictly judge a simple fart joke for creativity.
    [Tags]    tier:3    verify:llms    judging    simple
    ${joke}=    Creative.Ask For Joke    ${JOKE_PROMPTS}[0][prompt]    max_tokens=256
    ${score}    ${reason}=    Creative.Grade Joke
    ...    ${JOKE_PROMPTS}[0][prompt]    ${joke}    ${JUDGING_RUBRIC}[criteria]
    Log    Joke: ${joke} | Creativity Score: ${score} | Reason: ${reason}
    Should Be True    ${score} >= 0.3    Fart joke failed creativity judging: ${reason}

Judge Cross Domain Joke
    [Documentation]    Generate and strictly judge a science-cooking cross-domain joke.
    [Tags]    tier:3    verify:llms    judging    medium
    ${joke}=    Creative.Ask For Joke    ${JOKE_PROMPTS}[4][prompt]    max_tokens=512
    ${score}    ${reason}=    Creative.Grade Joke
    ...    ${JOKE_PROMPTS}[4][prompt]    ${joke}    ${JUDGING_RUBRIC}[criteria]
    Log    Joke: ${joke} | Creativity Score: ${score} | Reason: ${reason}
    Should Be True    ${score} >= 0.4    Cross-domain joke failed creativity judging: ${reason}

Judge Shakespearean Fart Joke
    [Documentation]    Generate and strictly judge the most complex creative joke.
    [Tags]    tier:3    verify:llms    judging    complex
    ${joke}=    Creative.Ask For Joke    ${JOKE_PROMPTS}[9][prompt]    max_tokens=2048
    ${score}    ${reason}=    Creative.Grade Joke
    ...    ${JOKE_PROMPTS}[9][prompt]    ${joke}    ${JUDGING_RUBRIC}[criteria]
    Log    Joke: ${joke} | Creativity Score: ${score} | Reason: ${reason}
    Should Be True    ${score} >= 0.4    Shakespearean fart joke failed creativity judging: ${reason}
