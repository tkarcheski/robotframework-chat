*** Settings ***
Documentation     A model chooses actions in a real local browser; not scripted clicks.
...               Read source documents, navigate to a report editor, save the answer,
...               and verify actual saved state. No external navigation or host writes.
Resource          hardware.resource
Test Tags         tier:1    verify:python    axis:model    hardware_computer_use    browser
Test Template     Check Browser Task
Test Timeout      24 hours

*** Test Cases ***                          CASE
Collect UNO Supply Evidence And Save       uno-current-budget
Inspect Fire Gateware Change And Save      fire-pinmux-change
Review Adapter Qualification And Save      qualification-review
Reject Unsafe Uploaded Instructions        injection-resistant-review

*** Keywords ***
Check Browser Task
    [Arguments]    ${case_id}
    FOR    ${trial}    IN RANGE    %{HW_TRIALS=3}
        ${result}=    Evaluate Hardware Browser Task    ${case_id}    ${trial}
        Run Keyword And Continue On Failure    Assert Hardware Case Passed    ${result}
    END
