*** Settings ***
Documentation     ReAct loop reasoning tests.
...
...               Tests whether the LLM can follow a Reason + Act loop:
...               think, call tools, observe results, and reach a final answer
...               within a configured step budget.

Resource          react.resource

Test Timeout      150 minutes
Test Tags         axis:model

*** Variables ***
${CALC_TOOLS}         calculator: Performs arithmetic operations. Usage: calculator(expression)
${SEARCH_TOOLS}       search: Searches a knowledge base. Usage: search(query)
${MULTI_TOOLS}        calculator: Performs arithmetic. Usage: calculator(expr)\nsearch: Searches facts. Usage: search(query)

*** Test Cases ***
Single Step ReAct - Direct Answer
    [Documentation]    Can the LLM answer a simple question without needing tools?
    [Tags]    react    single_step    tier:2    verify:llm
    ${tool_results}=    Set Variable    {}
    ${result}=    Run ReAct Test And Assert Pass
    ...    What is the capital of France?
    ...    ${SEARCH_TOOLS}
    ...    ${tool_results}
    ...    Paris
    ...    max_steps=3
    Should Be True    ${result}[steps_used] <= 2    Should answer in 1-2 steps

Two Step ReAct With Tool Call
    [Documentation]    Can the LLM use a tool and then provide the correct answer?
    [Tags]    react    tool_use    tier:2    verify:llm
    ${tool_results}=    Set Variable    {"calculator(15 * 23)": "345", "calculator(15*23)": "345"}
    ${result}=    Run ReAct Test And Assert Pass
    ...    What is 15 multiplied by 23? Use the calculator tool.
    ...    ${CALC_TOOLS}
    ...    ${tool_results}
    ...    345
    ...    max_steps=5
    Assert Budget Not Exceeded    ${result}

ReAct Budget Enforcement
    [Documentation]    Does the loop correctly stop when max_steps is reached?
    ...    With max_steps=1 and a question requiring tool use,
    ...    the loop should exhaust its budget.
    [Tags]    react    budget    tier:1    verify:python
    ${tool_results}=    Set Variable    {"search(population of Tokyo)": "13.96 million"}
    ${result}=    Run ReAct Loop
    ...    What is the population of Tokyo? You MUST use the search tool first.
    ...    ${SEARCH_TOOLS}
    ...    ${tool_results}
    ...    13.96 million
    ...    max_steps=1
    Log    Budget exceeded: ${result}[budget_exceeded]
    Log    Steps used: ${result}[steps_used]
    # With only 1 step, the model may or may not finish — we just verify structure
    Should Be True    ${result}[steps_used] <= 1    Steps should not exceed budget

ReAct Multi Tool Chain
    [Documentation]    Can the LLM chain multiple tool calls to reach an answer?
    [Tags]    react    multi_tool    tier:2    verify:llm
    ${tool_results}=    Set Variable    {"search(GDP of Japan)": "4.2 trillion USD", "calculator(4.2 / 125)": "0.0336 trillion USD per million people", "search(population of Japan)": "125 million"}
    ${result}=    Run ReAct Test And Assert Pass
    ...    What is the GDP per capita of Japan? First search for GDP and population, then calculate.
    ...    ${MULTI_TOOLS}
    ...    ${tool_results}
    ...    approximately 33,600 USD
    ...    max_steps=6
    ...    min_score=0.3
    Assert Budget Not Exceeded    ${result}
