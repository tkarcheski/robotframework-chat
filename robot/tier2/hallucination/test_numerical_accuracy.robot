*** Settings ***
Documentation     Numerical Accuracy Tests
...
...               Tests the LLM's ability to recall known numerical facts
...               accurately. Covers physics, chemistry, biology, history,
...               and mathematics. Extends the math test suite with factual
...               (not derived) numerics.

Resource          ../../resources/ask_and_validate.resource
Variables         ../../variables/numerical_facts.yaml

Default Tags      hallucination    numerical    tier:2    verify:llm

Test Timeout      100 minutes

*** Test Cases ***
Speed Of Light In Meters Per Second
    [Documentation]    The speed of light is exactly 299,792,458 m/s.
    [Tags]    tier:2    verify:llm    physics
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[0]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Year The Berlin Wall Fell
    [Documentation]    The Berlin Wall fell in 1989.
    [Tags]    tier:2    verify:llm    history
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[1]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Boiling Point Of Water In Celsius
    [Documentation]    Water boils at 100 degrees Celsius at standard pressure.
    [Tags]    tier:2    verify:llm    chemistry
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[2]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Number Of Human Chromosomes
    [Documentation]    A human somatic cell contains 46 chromosomes.
    [Tags]    tier:2    verify:llm    biology
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[3]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Value Of Pi To Five Decimal Places
    [Documentation]    Pi equals 3.14159 to five decimal places.
    [Tags]    tier:2    verify:llm    math
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[4]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Year The United Nations Was Founded
    [Documentation]    The United Nations was founded in 1945.
    [Tags]    tier:2    verify:llm    history
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[5]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Atomic Number Of Gold
    [Documentation]    Gold has atomic number 79.
    [Tags]    tier:2    verify:llm    chemistry
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[6]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Number Of Bones In Adult Human Body
    [Documentation]    The adult human body has 206 bones.
    [Tags]    tier:2    verify:llm    biology
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[7]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Year World War I Began
    [Documentation]    World War I began in 1914.
    [Tags]    tier:2    verify:llm    history
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[8]
    Ask And Validate    ${fact}[question]    ${fact}[expected]

Freezing Point Of Water In Fahrenheit
    [Documentation]    Water freezes at 32 degrees Fahrenheit.
    [Tags]    tier:2    verify:llm    physics
    ${fact}=    Set Variable    ${NUMERICAL_FACTS}[9]
    Ask And Validate    ${fact}[question]    ${fact}[expected]
