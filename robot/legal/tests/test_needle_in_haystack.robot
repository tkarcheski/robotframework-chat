*** Settings ***
Documentation     Needle-in-a-Haystack Legal Document Tests
...
...               Tests the LLM's ability to locate specific clauses, terms,
...               and provisions buried within a large software agreement.
...
...               Each test presents the full agreement text and asks the LLM
...               to find a specific "needle" — a clause that is deliberately
...               embedded among dense boilerplate language.

Resource          ../legal.resource

Default Tags      needle-in-haystack    tier:2    verify:llm

*** Test Cases ***

Find Auto-Renewal Clause
    [Documentation]    Can the LLM find the auto-renewal provision hidden in the payment section?
    [Tags]    difficulty:medium
    ${scenario}=    Set Variable    ${NEEDLE_SCENARIOS}[0]
    Run Needle Scenario    ${scenario}

Find Data Retention After Termination
    [Documentation]    Can the LLM find the perpetual data retention clause in the privacy section?
    [Tags]    difficulty:hard
    ${scenario}=    Set Variable    ${NEEDLE_SCENARIOS}[1]
    Run Needle Scenario    ${scenario}

Find Non-Compete Duration And Scope
    [Documentation]    Can the LLM find the non-compete obligation and its 24-month duration?
    [Tags]    difficulty:hard
    ${scenario}=    Set Variable    ${NEEDLE_SCENARIOS}[2]
    Run Needle Scenario    ${scenario}

Find Liability Cap Amount
    [Documentation]    Can the LLM identify the Licensor's maximum liability cap?
    [Tags]    difficulty:medium
    ${scenario}=    Set Variable    ${NEEDLE_SCENARIOS}[3]
    Run Needle Scenario    ${scenario}

Find Governing Law And Dispute Venue
    [Documentation]    Can the LLM identify the governing law and arbitration venue?
    [Tags]    difficulty:easy
    ${scenario}=    Set Variable    ${NEEDLE_SCENARIOS}[4]
    Run Needle Scenario    ${scenario}

Batch Needle-in-Haystack - All Scenarios
    [Documentation]    Can the LLM find all hidden clauses across the full agreement in batch?
    [Tags]    batch    template
    FOR    ${scenario}    IN    @{NEEDLE_SCENARIOS}
        Run Needle Scenario    ${scenario}
    END
