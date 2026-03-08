*** Settings ***
Documentation     Initial Robot Framework test for robotframework-chat MP.
Resource          ../math.resource

*** Test Cases ***
LLM Can Do Basic Math
    [Documentation]    Test that the LLM correctly answers a simple math question.
    Ask And Validate    What is 2 + 2?    4

LLM Can Do Another Simple Math
    [Documentation]    Test a second math question for regression.
    Ask And Validate    What is 5 + 7?    12
