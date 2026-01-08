*** Settings ***
Documentation     Comprehensive Robot Framework Math Test Suite for robotframework-chat with unique, progressively harder IQ questions.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           OperatingSystem
Library           String

*** Variables ***
${REPEAT_COUNT}   3
${SEED_START}     42
${SEED_END}       99

*** Keywords ***
Ask And Validate
    [Arguments]    ${question}    ${expected}
    ${answer}=     LLM.Ask LLM    ${question}
    ${score}    ${reason}=    LLM.Grade Answer    ${question}    ${expected}    ${answer}
    Should Be Equal As Integers    ${score}    1
    Log    Question: ${question} | Answer: ${answer} | Reason: ${reason}

Generate Random Integer
    [Arguments]    ${min}    ${max}
    ${rand}=    Evaluate    random.randint(${min}, ${max})    modules=random
    RETURN   ${rand}

*** Test Cases ***
IQ 100 Basic Addition
    [Tags]    IQ:100
    ${a}=    Generate Random Integer    -10000    10000
    ${b}=    Generate Random Integer    -10000    10000
    ${question}=    Set Variable    What is ${a} plus ${b}? Explain your steps.
    ${expected}=    Evaluate    ${a}+${b}
    Ask And Validate    ${question}    ${expected}

IQ 110 Simple Subtraction and Reasoning
    [Tags]    IQ:110
    ${x}=    Generate Random Integer    -10000    10000
    ${y}=    Generate Random Integer    -10000    10000
    ${question}=    Set Variable    Subtract ${y} from ${x} and explain why the result is correct.
    ${expected}=    Evaluate    ${x}-${y}
    Ask And Validate    ${question}    ${expected}

IQ 120 Multiplication Pattern Recognition
    [Tags]    IQ:120
    ${m}=    Generate Random Integer    -10000    10000
    ${n}=    Generate Random Integer    -10000    10000
    ${question}=    Set Variable    Multiply ${m} by ${n} and describe a pattern you notice in the result.
    ${expected}=    Evaluate    ${m}*${n}
    Ask And Validate    ${question}    ${expected}

IQ 130 Division with Remainders
    [Tags]    IQ:130
    ${num}=    Generate Random Integer    -10000    10000
    ${div}=    Generate Random Integer    -10000    10000
    ${question}=    Set Variable    Divide ${num} by ${div}. Give both quotient and remainder, explaining your reasoning.
    ${expected}=    Evaluate    ${num}//${div}
    Ask And Validate    ${question}    ${expected}

IQ 140 Simple Algebra: Solve for X
    [Tags]    IQ:140
    ${a}=    Generate Random Integer    -10000    10000
    ${b}=    Generate Random Integer    -10000    10000
    ${c}=    Generate Random Integer    -10000    10000
    ${question}=    Set Variable    Solve for x in the equation ${a}*x + ${b} = ${c} and explain each step.
    ${expected}=    Evaluate    (${c}-${b})/${a}
    Ask And Validate    ${question}    ${expected}

IQ 150 Nested Addition and Multiplication
    [Tags]    IQ:150
    ${p}=    Generate Random Integer    -10000    10000
    ${q}=    Generate Random Integer    -10000    10000
    ${r}=    Generate Random Integer    -10000    10000
    ${question}=    Set Variable    Compute (${p} + ${q}) * ${r}. Explain each calculation step.
    ${expected}=    Evaluate    (${p}+${q})*${r}
    Ask And Validate    ${question}    ${expected}