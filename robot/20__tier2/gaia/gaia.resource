*** Settings ***
Documentation     GAIA-style tool-use testing keywords and variables
...               Tests whether LLMs can correctly select and invoke Robot Framework
...               keywords when presented with tool descriptions in a prompt.

Library           rfc.gaia_keywords.GaiaKeywords
Variables         ${CURDIR}/variables/tool_definitions.yaml

*** Keywords ***
Run Single Tool Selection Test
    [Documentation]    Test that the LLM selects the correct single tool with correct arguments.
    ...                Uses a strict threshold (>= 0.9) so passing requires both correct
    ...                tool selection AND correct argument formatting — a 50/50 score of
    ...                0.5 (right tool, wrong args) must NOT pass.
    [Arguments]    ${tools}    ${question}    ${expected_tool}    ${expected_args}
    ${call}=    Create Dictionary    tool=${expected_tool}    arguments=${expected_args}
    ${expected_calls}=    Create List    ${call}
    ${score}    ${reason}    ${response}=    Run GAIA Tool Use Test
    ...    ${tools}    ${question}    ${expected_calls}
    Should Be True    ${score} >= 0.9
    ...    Tool selection or arguments failed (score=${score}): ${reason}
    Log    Score: ${score} | Reason: ${reason}
    RETURN    ${score}    ${reason}    ${response}

Run Multi Step Tool Test
    [Documentation]    Test that the LLM chains multiple tools in correct order with correct arguments.
    ...                Uses a strict threshold (>= 0.9) so reversed chains — which score
    ...                at most 0.5*0.5 + 0.5*1.0 = 0.75 under the heavy ordering penalty —
    ...                cannot pass even with perfect arguments.
    [Arguments]    ${tools}    ${question}    ${expected_calls}
    ${score}    ${reason}    ${response}=    Run GAIA Tool Use Test
    ...    ${tools}    ${question}    ${expected_calls}
    Should Be True    ${score} >= 0.9
    ...    Multi-step tool chain failed (score=${score}): ${reason}
    Log    Score: ${score} | Reason: ${reason}
    RETURN    ${score}    ${reason}    ${response}

Run Tool Refusal Test
    [Documentation]    Test that the LLM correctly refuses when no tool fits.
    [Arguments]    ${tools}    ${question}
    ${empty_list}=    Create List
    ${score}    ${reason}    ${response}=    Run GAIA Tool Use Test
    ...    ${tools}    ${question}    ${empty_list}
    Should Be True    ${score} >= 1.0
    ...    Model should have refused but made tool calls (score=${score}): ${reason}
    Log    Score: ${score} | Reason: ${reason}
    RETURN    ${score}    ${reason}    ${response}
