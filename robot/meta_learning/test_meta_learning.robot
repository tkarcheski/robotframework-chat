*** Settings ***
Documentation     Continual meta-learning probe tests.
...
...               Tests in-context skill retention: the model is taught a skill,
...               given a distractor, then tested on whether it can still apply
...               the skill correctly.

Resource          meta_learning.resource

Test Timeout      3 minutes

*** Test Cases ***
Simple Skill Retention - Formatting Rule
    [Documentation]    Teach a formatting rule, test recall after distractor.
    [Tags]    meta_learning    simple    tier:2    verify:llm
    Test Skill And Assert Retained
    ...    When I ask you to format a word, always surround it with triple asterisks like ***word***.
    ...    What is the largest planet in our solar system?
    ...    Please format the word "hello" for me.
    ...    ***hello***

Skill Retention With Long Distractor
    [Documentation]    Longer distractor conversation to stress skill retention.
    [Tags]    meta_learning    long_distractor    tier:2    verify:llm
    Test Skill And Assert Retained
    ...    Whenever I ask about an animal, start your response with "Fun fact:" followed by the answer.
    ...    Explain the difference between TCP and UDP protocols in networking. Include details about reliability, ordering, and use cases for each protocol.
    ...    Tell me about dolphins.
    ...    Fun fact:
    ...    min_score=0.3

Arithmetic Skill Retention
    [Documentation]    Teach a custom arithmetic rule, verify correct application.
    [Tags]    meta_learning    arithmetic    tier:2    verify:llm
    Test Skill And Assert Retained
    ...    When I give you a number X, always respond with X * 3 + 1. Just give the number, nothing else.
    ...    Who wrote the novel "1984"?
    ...    7
    ...    22

Skill Application - Classification Rule
    [Documentation]    Teach a classification rule, verify correct class assignment.
    [Tags]    meta_learning    classification    tier:2    verify:llm
    Test Skill And Assert Retained
    ...    Classify any food I mention as either WARM or COLD. Respond with only the classification word.
    ...    What year did the Berlin Wall fall?
    ...    Classify: ice cream
    ...    COLD
