*** Settings ***
Documentation     Event sequencing tests: order three events from earliest to latest.
...
...               Asks the LLM to sort three historical events chronologically.
...               The model must output the letter sequence (e.g. "A, B, C") on
...               the first line.  The sequence is extracted deterministically
...               and compared to the known-correct order, making these
...               Tier 1 / verify:python tests.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    sequencing    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Wright Brothers Then Sputnik Then Apollo
    [Documentation]    Airplane (1903) → Sputnik (1957) → Moon landing (1969): A, B, C.
    [Tags]    tier:1    verify:python    aviation_space
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[0]
    Assert Event Sequence Correct    ${s}

French Revolution Then Civil War Then World War II
    [Documentation]    French Revolution (1789) → US Civil War (1861) → WWII (1939): A, B, C.
    [Tags]    tier:1    verify:python    political_history
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[1]
    Assert Event Sequence Correct    ${s}

Telephone Then Radio Then Television
    [Documentation]    Telephone patent (1876) → Radio (1901) → Television demo (1926): A, B, C.
    [Tags]    tier:1    verify:python    communications_technology
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[2]
    Assert Event Sequence Correct    ${s}

Linux Then Google Then Facebook
    [Documentation]    Linux kernel (1991) → Google founded (1998) → Facebook launched (2004): A, B, C.
    [Tags]    tier:1    verify:python    software_history
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[3]
    Assert Event Sequence Correct    ${s}

Penicillin Then DNA Then PCR
    [Documentation]    Penicillin (1928) → DNA double helix (1953) → PCR (1985): A, B, C.
    [Tags]    tier:1    verify:python    science_history
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[4]
    Assert Event Sequence Correct    ${s}
