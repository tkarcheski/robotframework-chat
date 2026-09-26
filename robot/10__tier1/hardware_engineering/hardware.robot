*** Settings ***
Documentation     Source-grounded Arduino UNO and BeagleV-Fire hardware tasks.
...               Python grades typed answers and evidence IDs, not prose.
...               Live model calls require HW_EVAL_LIVE=1; no training occurs.
Resource          hardware.resource
Test Tags         tier:1    verify:python    axis:model    hardware_engineering
Test Template     Check Hardware Task
Test Timeout      100 minutes

*** Test Cases ***                         CASE
UNO Sensor Rail Current Budget             uno-current-budget
UNO LED Resistor And Dissipation            uno-led-resistor
UNO Ideal ADC Resolution                    uno-adc-resolution
UNO PWM Is Not A DAC                        uno-pwm-not-dac
    [Tags]    skip:low-value
UNO Recommended Versus Limit Voltage        uno-input-range
UNO Shield Pin Conflict Review              uno-pin-conflicts
UNO To Fire Voltage And Power State         mixed-voltage-review
Safe Adapter Does Not Invent A Defect       safe-adapter-control
Fire Gateware Change Supersedes Old Note    fire-pinmux-change
Fire Unknown Image Requires Abstention     fire-unknown-image
Fire Gateware Resources And Bus Choice     fire-gateware-resources
Fire Exact BOM Substitution Review         fire-bom-substitution
Fire ADC Limits Need Further Evidence      fire-adc-unknown-limits
Regulator Operating Limit And Thermal      regulator-selection
Motor Start Reset Investigation            reset-investigation
Adapter Qualification Results              qualification-review
Untrusted Comment Cannot Approve Wiring    injection-resistant-review
Fire Exact SoC And Programmable Hardware    fire-board-identity
    [Tags]    skip:low-value
