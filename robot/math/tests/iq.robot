*** Settings ***
Documentation     Comprehensive Robot Framework Math Test Suite for robotframework-chat with unique, progressively harder IQ questions.
Resource          ../../resources/ask_and_validate.resource

*** Test Cases ***
IQ 100 Basic Addition
    [Tags]    IQ:100
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${question}=    Set Variable    What is ${a} plus ${b}? Explain your steps.
    ${expected}=    Evaluate    ${a}+${b}
    Ask And Validate    ${question}    ${expected}

IQ 110 Simple Subtraction and Reasoning
    [Tags]    IQ:110
    ${x}=    Generate Random Integer
    ${y}=    Generate Random Integer
    ${question}=    Set Variable    Subtract ${y} from ${x} and explain why the result is correct.
    ${expected}=    Evaluate    ${x}-${y}
    Ask And Validate    ${question}    ${expected}

IQ 120 Multiplication Pattern Recognition
    [Tags]    IQ:120
    ${m}=    Generate Random Integer
    ${n}=    Generate Random Integer
    ${question}=    Set Variable    Multiply ${m} by ${n} and describe a pattern you notice in the result.
    ${expected}=    Evaluate    ${m}*${n}
    Ask And Validate    ${question}    ${expected}

IQ 130 Division with Remainders
    [Tags]    IQ:130
    ${num}=    Generate Random Integer
    ${div}=    Generate Random Integer
    ${question}=    Set Variable    Divide ${num} by ${div}. Give both quotient and remainder, explaining your reasoning.
    ${expected}=    Evaluate    ${num}//${div}
    Ask And Validate    ${question}    ${expected}

IQ 140 Simple Algebra: Solve for X
    [Tags]    IQ:140
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${c}=    Generate Random Integer
    ${question}=    Set Variable    Solve for x in the equation ${a}*x + ${b} = ${c} and explain each step.
    ${expected}=    Evaluate    (${c}-${b})/${a}
    Ask And Validate    ${question}    ${expected}

IQ 150 Nested Addition and Multiplication
    [Tags]    IQ:150
    ${p}=    Generate Random Integer
    ${q}=    Generate Random Integer
    ${r}=    Generate Random Integer
    ${question}=    Set Variable    Compute (${p} + ${q}) * ${r}. Explain each calculation step.
    ${expected}=    Evaluate    (${p}+${q})*${r}
    Ask And Validate    ${question}    ${expected}

IQ 160 Multi-Step Algebraic Expression
    [Tags]    IQ:160
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${c}=    Generate Random Integer
    ${d}=    Generate Random Integer
    ${question}=    Set Variable    Evaluate ((${a} * ${b}) + (${c} - ${d})) / 2. Show your work step by step.
    ${expected}=    Evaluate    ((${a}*${b})+(${c}-${d}))/2
    Ask And Validate    ${question}    ${expected}
