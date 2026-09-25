*** Settings ***
Library           rfc.hardware_eval_keywords.HardwareEvalKeywords    ${CURDIR}/fixtures

*** Keywords ***
Check Hardware Task
    [Arguments]    ${case_id}
    FOR    ${trial}    IN RANGE    %{HW_TRIALS=3}
        ${result}=    Evaluate Hardware Case    ${case_id}    0    spread    ${trial}
        Run Keyword And Continue On Failure    Assert Hardware Case Passed    ${result}
    END
