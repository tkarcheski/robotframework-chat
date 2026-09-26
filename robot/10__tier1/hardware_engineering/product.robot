*** Settings ***
Documentation     Product release decisions across revisions, budgets, timing and qualification.
...               Explicitly fictional project artifacts; no claim of real hardware validation.
Library           rfc.hardware_eval_keywords.HardwareEvalKeywords    ${CURDIR}/fixtures/product
Test Tags         tier:1    verify:python    axis:model    hardware_product
Test Template     Check Product Task
Test Timeout      100 minutes

*** Test Cases ***                       CASE
Firmware Battery Release                 battery-release
Revised Current Sensor Release           sensor-release
Sustained Telemetry Capacity Release      telemetry-release
Qualified Manufacturing BOM Release      manufacturing-release

*** Keywords ***
Check Product Task
    [Arguments]    ${case_id}
    FOR    ${trial}    IN RANGE    %{HW_TRIALS=3}
        ${result}=    Evaluate Hardware Case    ${case_id}    0    spread    ${trial}
        Run Keyword And Continue On Failure    Assert Hardware Case Passed    ${result}
    END
