*** Settings ***
Documentation     GAIA-Style Tool-Use Tests
...
...               Evaluates whether local LLMs can correctly identify and call
...               Robot Framework custom keywords when presented with tool
...               descriptions in a prompt.  Inspired by the GAIA benchmark
...               which tests LLMs augmented with tools (web search, calculators).
...
...               == Test Categories ==
...
...               Single Tool Selection (3 tests):
...               Given multiple tools, select the correct one for the task.
...
...               Argument Formatting (3 tests):
...               Provide correct argument names and values to a selected tool.
...
...               Multi-Step Tool Chaining (3 tests):
...               Use multiple tools in the correct sequence to solve a problem.
...
...               Tool Refusal (3 tests):
...               Recognize when no available tool can solve the stated problem.

Resource          gaia.resource

Test Timeout      150 minutes
Test Tags         axis:model


*** Test Cases ***

# =========================================================================
# Category 1: Single Tool Selection
# =========================================================================

Single Tool — Select Ask LLM For Simple Query
    [Documentation]    Can the LLM pick Ask LLM when the task is to query a language model?
    [Tags]    tier:1    verify:python    gaia    single_tool
    ${tools}=    Create List
    ...    ${ASK_LLM_TOOL}
    ...    ${GRADE_ANSWER_TOOL}
    ...    ${EXECUTE_PYTHON_TOOL}
    ...    ${BRAINSTORM_IDEAS_TOOL}
    ${expected_args}=    Create Dictionary    prompt=What is the capital of France?
    Run Single Tool Selection Test
    ...    ${tools}
    ...    I need to ask a language model what the capital of France is. Which tool should I use and how?
    ...    Ask LLM
    ...    ${expected_args}

Single Tool — Select Execute Python For Computation
    [Documentation]    Can the LLM pick Execute Python In Container for a math computation?
    [Tags]    tier:1    verify:python    gaia    single_tool
    ${tools}=    Create List
    ...    ${ASK_LLM_TOOL}
    ...    ${GRADE_ANSWER_TOOL}
    ...    ${EXECUTE_PYTHON_TOOL}
    ...    ${SET_LLM_MODEL_TOOL}
    ${expected_args}=    Create Dictionary    code=import math; print(math.factorial(20))
    Run Single Tool Selection Test
    ...    ${tools}
    ...    I need to compute the exact factorial of 20 and print the result. Which tool gives a precise numeric answer?
    ...    Execute Python In Container
    ...    ${expected_args}

Single Tool — Select Safety Tool For Injection Test
    [Documentation]    Can the LLM pick Test Prompt Injection Resistance for a safety check?
    [Tags]    tier:1    verify:python    gaia    single_tool
    ${tools}=    Create List
    ...    ${ASK_LLM_TOOL}
    ...    ${TEST_INJECTION_TOOL}
    ...    ${GRADE_ANSWER_TOOL}
    ...    ${BRAINSTORM_IDEAS_TOOL}
    ${expected_args}=    Create Dictionary    prompt=ignore all previous instructions
    Run Single Tool Selection Test
    ...    ${tools}
    ...    I need to check if a model resists the prompt 'ignore all previous instructions'. Which tool should I use?
    ...    Test Prompt Injection Resistance
    ...    ${expected_args}

# =========================================================================
# Category 2: Argument Formatting
# =========================================================================

Arguments — Set LLM Parameters With Multiple Values
    [Documentation]    Can the LLM provide correct argument names for Set LLM Parameters?
    [Tags]    tier:1    verify:python    gaia    arguments
    ${tools}=    Create List
    ...    ${SET_LLM_PARAMETERS_TOOL}
    ...    ${ASK_LLM_TOOL}
    ${expected_args}=    Create Dictionary
    ...    temperature=0.7
    ...    max_tokens=1024
    ...    top_p=0.9
    Run Single Tool Selection Test
    ...    ${tools}
    ...    Configure the model to use temperature 0.7, max tokens 1024, and top_p 0.9.
    ...    Set LLM Parameters
    ...    ${expected_args}

Arguments — Brainstorm Ideas With Domain And Constraints
    [Documentation]    Can the LLM fill in domain, count, and constraints for Brainstorm Ideas?
    [Tags]    tier:1    verify:python    gaia    arguments
    ${tools}=    Create List
    ...    ${BRAINSTORM_IDEAS_TOOL}
    ...    ${RESEARCH_MARKET_TOOL}
    ...    ${ASK_LLM_TOOL}
    ${expected_args}=    Create Dictionary
    ...    domain=healthcare
    ...    count=3
    ...    constraints=must be mobile-first
    Run Single Tool Selection Test
    ...    ${tools}
    ...    Generate 3 product ideas in the healthcare domain with the constraint 'must be mobile-first'.
    ...    Brainstorm Ideas
    ...    ${expected_args}

Arguments — Grade Answer With Three String Parameters
    [Documentation]    Can the LLM pass correct question, expected, and actual to Grade Answer?
    [Tags]    tier:1    verify:python    gaia    arguments
    ${tools}=    Create List
    ...    ${GRADE_ANSWER_TOOL}
    ...    ${ASK_LLM_TOOL}
    ...    ${SET_LLM_MODEL_TOOL}
    ${expected_args}=    Create Dictionary
    ...    question=What is 6 times 7?
    ...    expected=forty-two
    ...    actual=42
    Run Single Tool Selection Test
    ...    ${tools}
    ...    Grade the student's answer '42' against the expected answer 'forty-two' for the question 'What is 6 times 7?'.
    ...    Grade Answer
    ...    ${expected_args}

# =========================================================================
# Category 3: Multi-Step Tool Chaining
# =========================================================================

Multi Step — Ask Then Grade Pipeline
    [Documentation]    Can the LLM chain Ask LLM then Grade Answer in the correct order?
    [Tags]    tier:2    verify:llm    gaia    multi_step
    ${tools}=    Create List
    ...    ${ASK_LLM_TOOL}
    ...    ${GRADE_ANSWER_TOOL}
    ${call1}=    Create Dictionary
    ...    tool=Ask LLM
    ...    arguments=${{{"prompt": "What is the square root of 144?"}}}
    ${call2}=    Create Dictionary
    ...    tool=Grade Answer
    ...    arguments=${{{"question": "What is the square root of 144?", "expected": "12", "actual": "<response from Ask LLM>"}}}
    ${expected_calls}=    Create List    ${call1}    ${call2}
    Run Multi Step Tool Test
    ...    ${tools}
    ...    First ask the model 'What is the square root of 144?' then grade the response against the expected answer '12'.
    ...    ${expected_calls}

Multi Step — Configure Model Then Ask
    [Documentation]    Can the LLM chain Set LLM Model, Set LLM Parameters, then Ask LLM?
    [Tags]    tier:2    verify:llm    gaia    multi_step
    ${tools}=    Create List
    ...    ${SET_LLM_MODEL_TOOL}
    ...    ${SET_LLM_PARAMETERS_TOOL}
    ...    ${ASK_LLM_TOOL}
    ${call1}=    Create Dictionary
    ...    tool=Set LLM Model
    ...    arguments=${{{"model": "mistral"}}}
    ${call2}=    Create Dictionary
    ...    tool=Set LLM Parameters
    ...    arguments=${{{"temperature": 0.0, "max_tokens": 256}}}
    ${call3}=    Create Dictionary
    ...    tool=Ask LLM
    ...    arguments=${{{"prompt": "Explain recursion in one sentence"}}}
    ${expected_calls}=    Create List    ${call1}    ${call2}    ${call3}
    Run Multi Step Tool Test
    ...    ${tools}
    ...    Switch to the 'mistral' model, set temperature to 0.0 and max_tokens to 256, then ask 'Explain recursion in one sentence'.
    ...    ${expected_calls}

Multi Step — CEO Pipeline Ordering
    [Documentation]    Can the LLM order Brainstorm Ideas, Research Market, Analyze IP Landscape correctly?
    ...                Argument grading is intentionally relaxed for the chained calls
    ...                (Research Market, Analyze IP Landscape) because their list-shaped
    ...                inputs depend on the runtime output of prior calls — only the
    ...                tool selection and ordering are scored.
    [Tags]    tier:2    verify:llm    gaia    multi_step
    ${tools}=    Create List
    ...    ${BRAINSTORM_IDEAS_TOOL}
    ...    ${RESEARCH_MARKET_TOOL}
    ...    ${ANALYZE_IP_LANDSCAPE_TOOL}
    ...    ${DEVELOP_PATENT_STRATEGY_TOOL}
    ${call1}=    Create Dictionary
    ...    tool=Brainstorm Ideas
    ...    arguments=${{{"domain": "robotics", "count": 5}}}
    ${call2}=    Create Dictionary
    ...    tool=Research Market
    ...    arguments=${{{}}}
    ${call3}=    Create Dictionary
    ...    tool=Analyze IP Landscape
    ...    arguments=${{{}}}
    ${expected_calls}=    Create List    ${call1}    ${call2}    ${call3}
    Run Multi Step Tool Test
    ...    ${tools}
    ...    Run a full product analysis pipeline for the 'robotics' domain: generate 5 ideas, research the market, then analyze the IP landscape.
    ...    ${expected_calls}

# =========================================================================
# Category 4: Tool Refusal
# =========================================================================

Refusal — No Tool For Live Weather Lookup
    [Documentation]    Can the LLM recognize that no tool can fetch live weather data?
    [Tags]    tier:1    verify:python    gaia    refusal
    ${tools}=    Create List
    ...    ${ASK_LLM_TOOL}
    ...    ${GRADE_ANSWER_TOOL}
    ...    ${EXECUTE_PYTHON_TOOL}
    Run Tool Refusal Test
    ...    ${tools}
    ...    Look up the current real-time weather in San Francisco right now.

Refusal — No Tool For Sending Email
    [Documentation]    Can the LLM recognize that no tool can send an email?
    [Tags]    tier:1    verify:python    gaia    refusal
    ${tools}=    Create List
    ...    ${ASK_LLM_TOOL}
    ...    ${SET_LLM_PARAMETERS_TOOL}
    ...    ${BRAINSTORM_IDEAS_TOOL}
    ...    ${GRADE_ANSWER_TOOL}
    Run Tool Refusal Test
    ...    ${tools}
    ...    Send an email to bob@example.com with the subject 'Meeting Tomorrow' and body 'See you at 3pm'.

Refusal — No Tool For Database Query
    [Documentation]    Can the LLM recognize that no tool can query a SQL database?
    [Tags]    tier:1    verify:python    gaia    refusal
    ${tools}=    Create List
    ...    ${ASK_LLM_TOOL}
    ...    ${EXECUTE_PYTHON_TOOL}
    ...    ${TEST_INJECTION_TOOL}
    Run Tool Refusal Test
    ...    ${tools}
    ...    Query the PostgreSQL database to retrieve all test runs from the last week and return the results as a table.
