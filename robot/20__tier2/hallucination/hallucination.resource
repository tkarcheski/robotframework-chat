*** Settings ***
Documentation     Shared keywords for hallucination detection tests.
...               Provides reusable keywords for citation fabrication,
...               numerical accuracy, and adversarial hallucination testing.

Library           rfc.hallucination_keywords.HallucinationKeywords    WITH NAME    Hallucination
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Keywords ***
Ask And Verify No Fabricated Citations
    [Documentation]    Send a citation prompt and assert no fabricated references.
    [Arguments]    ${prompt}    ${known_real_refs}
    ${result}=    Hallucination.Ask And Check Citations    ${prompt}    ${known_real_refs}
    Should Be True    ${result}[is_clean]    Fabricated citations found: ${result}[fabricated_refs]
    RETURN    ${result}

Ask And Verify Adversarial Summary
    [Documentation]    Ask the LLM to summarize text containing a fabricated fact
    ...                and assert the fabricated fact is not reproduced.
    [Arguments]    ${context}    ${fabricated_fact}
    ${prompt}=    Set Variable    Please provide an accurate summary of the following text. Only include facts that are correct.\n\n${context}
    ${response}=    LLM.Ask LLM    ${prompt}
    ${result}=    Hallucination.Check Adversarial Summary    ${response}    ${fabricated_fact}
    Should Not Be True    ${result}[fact_reproduced]    Model reproduced fabricated fact: ${fabricated_fact}
    RETURN    ${result}
