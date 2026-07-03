*** Settings ***
Documentation     Progressive IQ-based math tests with randomized inputs
Resource          math.resource
Library           Collections
Library           OperatingSystem
Library           String

*** Test Cases ***
IQ 70 Basic Addition
    [Documentation]    Can the LLM compute {a} plus {b} and explain its steps?
    [Tags]    IQ:70    tier:2    verify:llm
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${question}=    Set Variable    What is ${a} plus ${b}? Explain your steps.
    ${expected}=    Evaluate    ${a}+${b}
    Ask And Validate    ${question}    ${expected}

IQ 80 Simple Subtraction and Reasoning
    [Documentation]    Can the LLM subtract {y} from {x} and explain why the result is correct?
    [Tags]    IQ:80    tier:2    verify:llm
    ${x}=    Generate Random Integer
    ${y}=    Generate Random Integer
    ${question}=    Set Variable    Subtract ${y} from ${x} and explain why the result is correct.
    ${expected}=    Evaluate    ${x}-${y}
    Ask And Validate    ${question}    ${expected}

IQ 90 Multiplication Pattern Recognition
    [Documentation]    Can the LLM multiply {m} by {n} and describe a pattern in the result?
    [Tags]    IQ:90    tier:2    verify:llm
    ${m}=    Generate Random Integer
    ${n}=    Generate Random Integer
    ${question}=    Set Variable    Multiply ${m} by ${n} and describe a pattern you notice in the result.
    ${expected}=    Evaluate    ${m}*${n}
    Ask And Validate    ${question}    ${expected}

IQ 100 Division with Remainders
    [Documentation]    Can the LLM divide {num} by {div} and give both quotient and remainder?
    [Tags]    IQ:100    tier:2    verify:llm
    ${num}=    Generate Random Integer
    ${div}=    Generate Random Integer
    ${question}=    Set Variable    Divide ${num} by ${div}. Give both quotient and remainder, explaining your reasoning.
    ${expected}=    Evaluate    ${num}//${div}
    Ask And Validate    ${question}    ${expected}

IQ 110 Simple Algebra: Solve for X
    [Documentation]    Can the LLM solve for x in {a}*x + {b} = {c} and explain each step?
    [Tags]    IQ:110    tier:2    verify:llm
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${c}=    Generate Random Integer
    ${question}=    Set Variable    Solve for x in the equation ${a}*x + ${b} = ${c} and explain each step.
    ${expected}=    Evaluate    (${c}-${b})/${a}
    Ask And Validate    ${question}    ${expected}

IQ 130 Nested Addition and Multiplication
    [Documentation]    Can the LLM compute ({p} + {q}) * {r} and explain each calculation step?
    [Tags]    IQ:130    tier:2    verify:llm
    ${p}=    Generate Random Integer
    ${q}=    Generate Random Integer
    ${r}=    Generate Random Integer
    ${question}=    Set Variable    Compute (${p} + ${q}) * ${r}. Explain each calculation step.
    ${expected}=    Evaluate    (${p}+${q})*${r}
    Ask And Validate    ${question}    ${expected}

IQ 150 Multi-Step Algebraic Expression
    [Documentation]    Can the LLM evaluate (({a} * {b}) + ({c} - {d})) / 2 showing work step by step?
    [Tags]    IQ:150    tier:2    verify:llm
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${c}=    Generate Random Integer
    ${d}=    Generate Random Integer
    ${question}=    Set Variable    Evaluate ((${a} * ${b}) + (${c} - ${d})) / 2. Show your work step by step.
    ${expected}=    Evaluate    ((${a}*${b})+(${c}-${d}))/2
    Ask And Validate    ${question}    ${expected}
