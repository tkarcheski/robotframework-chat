*** Settings ***
Documentation     Shared keywords for context window stress testing.
...               Probes how LLM retrieval degrades as context fills up.
...               Tests "lost in the middle" effect via needles at various positions
...               within increasing amounts of filler content.

Library           rfc.context_window_keywords.ContextWindowKeywords    WITH NAME    CtxWindow
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Keywords ***
Probe Needle At Fill Level
    [Documentation]    Test needle retrieval at a specific fill percentage.
    ...                Builds a filled prompt, queries the LLM, checks recall,
    ...                and emits metrics. No assertion — test handles expectations.
    [Arguments]    ${case}    ${fill_pct}    ${position}    ${context_window}
    LLM.Set LLM Parameters    num_ctx=${context_window}    max_tokens=256    temperature=0.0
    ${result}=    CtxWindow.Ask At Fill Level
    ...    ${case}[needle_fact]
    ...    ${case}[question]
    ...    ${case}[expected_answer]
    ...    ${fill_pct}
    ...    ${position}
    ...    ${context_window}
    RETURN    ${result}

Assert Needle Recalled
    [Documentation]    Assert that the needle was successfully retrieved.
    [Arguments]    ${result}
    Should Be True    ${result}[recalled]
    ...    Needle not recalled. Response: ${result}[response]

Assert Needle Not Recalled
    [Documentation]    Assert that the needle was NOT retrieved.
    [Arguments]    ${result}
    Should Not Be True    ${result}[recalled]
    ...    Unexpectedly recalled needle. Response: ${result}[response]
