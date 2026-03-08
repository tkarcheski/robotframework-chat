*** Settings ***
Documentation     Advanced math tests covering percentages, exponents, geometry, statistics, and sequences.
Resource          ../../resources/ask_and_validate.resource

*** Test Cases ***
IQ 105 Percentage Calculation
    [Tags]    IQ:105
    ${whole}=    Generate Positive Integer
    ${pct}=      Generate Random Percent
    ${question}=    Set Variable    What is ${pct}% of ${whole}? Give only the numeric answer.
    ${expected}=    Evaluate    ${whole} * ${pct} / 100
    Ask And Validate    ${question}    ${expected}

IQ 115 Exponentiation
    [Tags]    IQ:115
    ${base}=    Generate Small Positive Integer    min=2    max=20
    ${exp}=     Generate Small Positive Integer    min=2    max=5
    ${question}=    Set Variable    What is ${base} raised to the power of ${exp}? Give only the numeric answer.
    ${expected}=    Evaluate    ${base} ** ${exp}
    Ask And Validate    ${question}    ${expected}

IQ 115 Square Root Of Perfect Square
    [Tags]    IQ:115
    ${n}=       Generate Small Positive Integer    min=2    max=100
    ${squared}=    Evaluate    ${n} ** 2
    ${question}=   Set Variable    What is the square root of ${squared}? Give only the numeric answer.
    ${expected}=   Set Variable    ${n}
    Ask And Validate    ${question}    ${expected}

IQ 135 Order Of Operations PEMDAS
    [Tags]    IQ:135
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${c}=    Generate Random Integer
    ${d}=    Generate Random Integer
    ${question}=    Set Variable    Evaluate: ${a} + ${b} * ${c} - ${d}. Follow standard order of operations. Give only the numeric answer.
    ${expected}=    Evaluate    ${a} + ${b} * ${c} - ${d}
    Ask And Validate    ${question}    ${expected}

IQ 110 Absolute Value
    [Tags]    IQ:110
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${question}=    Set Variable    What is the absolute value of ${a} minus ${b}? Give only the numeric answer.
    ${expected}=    Evaluate    abs(${a} - ${b})
    Ask And Validate    ${question}    ${expected}

IQ 125 Greatest Common Divisor
    [Tags]    IQ:125
    ${a}=    Generate Positive Integer
    ${b}=    Generate Positive Integer
    ${question}=    Set Variable    What is the greatest common divisor of ${a} and ${b}? Give only the numeric answer.
    ${expected}=    Evaluate    math.gcd(${a}, ${b})    modules=math
    Ask And Validate    ${question}    ${expected}

IQ 125 Arithmetic Mean
    [Tags]    IQ:125
    ${a}=    Generate Random Integer
    ${b}=    Generate Random Integer
    ${c}=    Generate Random Integer
    ${d}=    Generate Random Integer
    ${e}=    Generate Random Integer
    ${question}=    Set Variable    What is the arithmetic mean of ${a}, ${b}, ${c}, ${d}, and ${e}? Give the numeric answer.
    ${expected}=    Evaluate    (${a} + ${b} + ${c} + ${d} + ${e}) / 5
    Ask And Validate    ${question}    ${expected}

IQ 105 Rectangle Area
    [Tags]    IQ:105
    ${l}=    Generate Positive Integer    min=1    max=500
    ${w}=    Generate Positive Integer    min=1    max=500
    ${question}=    Set Variable    What is the area of a rectangle with length ${l} and width ${w}? Give only the numeric answer.
    ${expected}=    Evaluate    ${l} * ${w}
    Ask And Validate    ${question}    ${expected}

IQ 120 Rectangular Prism Volume
    [Tags]    IQ:120
    ${l}=    Generate Positive Integer    min=1    max=100
    ${w}=    Generate Positive Integer    min=1    max=100
    ${h}=    Generate Positive Integer    min=1    max=100
    ${question}=    Set Variable    What is the volume of a rectangular prism with length ${l}, width ${w}, and height ${h}? Give only the numeric answer.
    ${expected}=    Evaluate    ${l} * ${w} * ${h}
    Ask And Validate    ${question}    ${expected}

IQ 145 Sum Of Arithmetic Sequence
    [Tags]    IQ:145
    ${a}=    Generate Small Positive Integer    min=1    max=100
    ${d}=    Generate Small Positive Integer    min=1    max=20
    ${n}=    Generate Small Positive Integer    min=5    max=20
    ${question}=    Set Variable    What is the sum of the first ${n} terms of an arithmetic sequence starting at ${a} with a common difference of ${d}? Give only the numeric answer.
    ${expected}=    Evaluate    ${n} * (2 * ${a} + (${n} - 1) * ${d}) / 2
    Ask And Validate    ${question}    ${expected}
