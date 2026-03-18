*** Settings ***
Documentation     Initial Robot Framework test for robotframework-chat MP.
Resource          ../math.resource

*** Test Cases ***
LLM Can Do Basic Math
    [Documentation]    Can the LLM correctly answer 'What is 2 + 2?'?
    Ask And Validate    What is 2 + 2?    4

LLM Can Do Another Simple Math
    [Documentation]    Can the LLM correctly answer 'What is 5 + 7?'?
    Ask And Validate    What is 5 + 7?    12
