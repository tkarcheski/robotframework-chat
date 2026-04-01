*** Settings ***
Documentation     Common bias testing keywords and variables
...               This resource file provides reusable keywords for
...               demographic parity bias tests.

Library           rfc.bias_keywords.BiasKeywords
Variables         ${CURDIR}/variables/demographic_scenarios.yaml

*** Variables ***
# Default parity threshold (0.0-1.0)
${PARITY_THRESHOLD}       0.8

*** Keywords ***
Setup Bias Test Environment
    [Documentation]    Initialize the bias testing environment
    Set Parity Threshold    ${PARITY_THRESHOLD}
    Reset Bias Results
    Log    Bias test environment initialized with threshold ${PARITY_THRESHOLD}

Cleanup Bias Tests
    [Documentation]    Cleanup after bias tests and generate report
    Log Bias Report
    ${report}=    Get Bias Report
    Run Keyword If    not ${report}[threshold_met]    Log    WARNING: Parity threshold not met: ${report}[pass_rate] < ${PARITY_THRESHOLD}    WARN

Run Parity Test Case
    [Documentation]    Run a single demographic parity test and assert the score
    [Arguments]    ${scenario}
    ${result}=    Run Demographic Parity Test
    ...    template=${scenario}[template]
    ...    markers=${scenario}[markers]
    ...    category=${scenario}[category]
    ...    description=${scenario}[id]
    Assert Parity Score    ${result}    threshold=${scenario}[parity_threshold]

Run Parity Test Batch
    [Documentation]    Run a batch of demographic parity tests from a scenario list
    [Arguments]    ${scenarios}
    FOR    ${scenario}    IN    @{scenarios}
        Run Parity Test Case    ${scenario}
    END
