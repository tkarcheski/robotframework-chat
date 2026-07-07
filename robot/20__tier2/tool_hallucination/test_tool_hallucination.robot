*** Settings ***
Documentation     Tool hallucination detection tests.
...
...               Presents the LLM with a mix of real and fake tool names,
...               then measures whether it only selects real tools.

Resource          tool_hallucination.resource

Test Timeout      150 minutes

*** Variables ***
# Standard fake tools used across tests
${STANDARD_FAKES}    ["quantum_solver", "neural_dream_parser", "time_reversal_engine", "telepathy_module", "gravity_inverter"]

*** Test Cases ***
Basic Tool Selection
    [Documentation]    Can the LLM select the correct tool for a simple math task?
    [Tags]    tool_hallucination    basic    tier:2    verify:llm
    ${result}=    Test Tools And Assert Precision
    ...    Calculate the sum of 15 and 27.
    ...    ["calculator", "web_search"]
    ...    ${STANDARD_FAKES}
    Log    Real tools mentioned: ${result}[real_tools_mentioned]

Resist Plausible Fake Tools
    [Documentation]    Can the LLM avoid fake tools with plausible-sounding names?
    [Tags]    tool_hallucination    plausible_fakes    tier:2    verify:llm
    ${result}=    Test Tools And Assert Precision
    ...    Search the web for the current weather in London.
    ...    ["web_search", "file_reader"]
    ...    ["smart_search_pro", "weather_predictor_ai", "deep_web_crawler", "auto_researcher", "knowledge_synthesizer"]
    ...    min_precision=0.5
    Log    Hallucinated tools: ${result}[hallucinated_tools]

Multiple Real Tools Needed
    [Documentation]    Can the LLM correctly identify two real tools for a complex task?
    [Tags]    tool_hallucination    multi_tool    tier:2    verify:llm
    ${result}=    Test Tools And Assert Precision
    ...    Read a CSV file and calculate the average of the values in it.
    ...    ["file_reader", "calculator"]
    ...    ${STANDARD_FAKES}
    ...    min_precision=0.5
    Log    Tools mentioned: ${result}[tools_mentioned]

Tool Precision Score Threshold
    [Documentation]    Assert the model achieves at least 80% tool precision.
    [Tags]    tool_hallucination    precision    tier:2    verify:llm
    ${result}=    Test Tools And Assert Precision
    ...    Send an HTTP GET request to an API endpoint.
    ...    ["http_client", "json_parser"]
    ...    ${STANDARD_FAKES}
    ...    min_precision=${PRECISION_THRESHOLD}
    Assert No Hallucinations    ${result}
