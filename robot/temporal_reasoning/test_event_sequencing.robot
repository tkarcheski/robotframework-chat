*** Settings ***
Documentation     Event sequencing tests: order three events from earliest to latest.
...
...               Asks the LLM to sort three historical events chronologically.
...               The model must output the letter sequence (e.g. "A, B, C") on
...               the first line.  The sequence is extracted deterministically
...               and compared to the known-correct order, making these
...               Tier 1 / verify:python tests.
...
...               Events are deliberately presented in non-chronological order
...               for several scenarios so that a model cannot pass by always
...               answering "A, B, C" without doing any temporal reasoning.
...               Expected orderings: A,B,C / B,C,A / B,C,A / A,B,C / C,A,B

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    sequencing    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Wright Brothers Then Sputnik Then Apollo
    [Documentation]    Airplane (1903) → Sputnik (1957) → Moon landing (1969): A, B, C.
    [Tags]    tier:1    verify:python    aviation_space
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[0]
    Assert Event Sequence Correct    ${s}

WWII Presented First But French Revolution Came First
    [Documentation]    Events given as WWII(A)/French Revolution(B)/Civil War(C). Correct order is B, C, A.
    [Tags]    tier:1    verify:python    political_history    scrambled
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[1]
    Assert Event Sequence Correct    ${s}

Television Presented First But Telephone Came First
    [Documentation]    Events given as Television(A)/Telephone(B)/Radio(C). Correct order is B, C, A.
    [Tags]    tier:1    verify:python    communications_technology    scrambled
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[2]
    Assert Event Sequence Correct    ${s}

Linux Then Google Then Facebook
    [Documentation]    Linux kernel (1991) → Google founded (1998) → Facebook launched (2004): A, B, C.
    [Tags]    tier:1    verify:python    software_history
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[3]
    Assert Event Sequence Correct    ${s}

PCR Presented Last But Penicillin Came First
    [Documentation]    Events given as DNA(A)/PCR(B)/Penicillin(C). Correct order is C, A, B.
    [Tags]    tier:1    verify:python    science_history    scrambled
    ${s}=    Set Variable    ${SEQUENCE_SCENARIOS}[4]
    Assert Event Sequence Correct    ${s}
