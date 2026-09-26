*** Settings ***
Documentation     Paired identical-byte context stress using public board evidence.
...               Full matrix is opt-in with HW_CONTEXT_SWEEP=1.
...               All tasks, four evidence positions, three repetitions by default.
...               Unsupported lengths are SKIP/incomplete, never correctness passes.
Resource          hardware.resource
Library           String
Test Tags         tier:1    verify:python    axis:model    hardware_context    stress
Test Template     Check Context Level
Test Timeout      24 hours

*** Variables ***
${TRIALS}         %{HW_TRIALS=3}
${POSITIONS}      %{HW_POSITIONS=start,middle,end,spread}
${CASES}          %{HW_CONTEXT_CASES=all}

*** Test Cases ***          TOTAL CONTEXT
Hardware Context 4K        4096
Hardware Context 8K        8192
Hardware Context 16K       16384
Hardware Context 32K       32768
Hardware Context 64K       65536
Hardware Context 128K      131072
Hardware Context 262K      262144
Hardware Context 524K      524288
Hardware Context 1M        1000000

*** Keywords ***
Check Context Level
    [Arguments]    ${context}
    Skip If    '%{HW_CONTEXT_SWEEP=0}' != '1'    Set HW_CONTEXT_SWEEP=1 for the explicit long-context matrix.
    IF    '${CASES}' == 'all'
        ${ids}=    Get Hardware Case Ids
    ELSE
        ${ids}=    Split String    ${CASES}    ,
    END
    ${positions}=    Split String    ${POSITIONS}    ,
    FOR    ${case_id}    IN    @{ids}
        FOR    ${position}    IN    @{positions}
            FOR    ${trial}    IN RANGE    ${TRIALS}
                ${result}=    Evaluate Hardware Case    ${case_id}    ${context}    ${position}    ${trial}
                Run Keyword And Continue On Failure    Assert Hardware Case Passed    ${result}
            END
        END
    END
