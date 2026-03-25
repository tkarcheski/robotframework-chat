*** Settings ***
Documentation     Loophole Detection Legal Document Tests
...
...               Tests the LLM's ability to identify contradictions, overreach,
...               imbalances, and exploitable ambiguities within a software agreement.
...
...               Each test presents the full agreement text and asks the LLM
...               to analyze specific clauses for loopholes that a careful legal
...               reviewer should catch.

Resource          ../legal.resource

Default Tags      loophole-detection    tier:2    verify:llm

*** Test Cases ***

Detect Contradictory Liability And Indemnification
    [Documentation]    Can the LLM find the contradiction between the liability cap and unlimited indemnification?
    [Tags]    contradiction    difficulty:hard
    ${scenario}=    Set Variable    ${LOOPHOLE_SCENARIOS}[0]
    Run Loophole Scenario    ${scenario}

Detect Overbroad IP Assignment
    [Documentation]    Can the LLM identify the overreaching IP assignment that captures independently created works?
    [Tags]    overreach    difficulty:hard
    ${scenario}=    Set Variable    ${LOOPHOLE_SCENARIOS}[1]
    Run Loophole Scenario    ${scenario}

Detect One-Sided Indemnification
    [Documentation]    Can the LLM identify that indemnification only protects the Licensor?
    [Tags]    imbalance    difficulty:medium
    ${scenario}=    Set Variable    ${LOOPHOLE_SCENARIOS}[2]
    Run Loophole Scenario    ${scenario}

Detect Unilateral Amendment Power
    [Documentation]    Can the LLM spot the clause allowing Licensor to change terms unilaterally?
    [Tags]    overreach    difficulty:medium
    ${scenario}=    Set Variable    ${LOOPHOLE_SCENARIOS}[3]
    Run Loophole Scenario    ${scenario}

Detect Arbitration Venue And Cost Imbalance
    [Documentation]    Can the LLM identify the multiple imbalances in the dispute resolution clause?
    [Tags]    imbalance    difficulty:hard
    ${scenario}=    Set Variable    ${LOOPHOLE_SCENARIOS}[4]
    Run Loophole Scenario    ${scenario}

Batch Loophole Detection - All Scenarios
    [Documentation]    Can the LLM detect all loophole types across the full agreement in batch?
    [Tags]    batch    template
    FOR    ${scenario}    IN    @{LOOPHOLE_SCENARIOS}
        Run Loophole Scenario    ${scenario}
    END
