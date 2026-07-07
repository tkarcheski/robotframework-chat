*** Settings ***
Documentation     Shared keywords and configuration for epistemic calibration tests.

Library           rfc.epistemic_calibration_keywords.EpistemicCalibrationKeywords    WITH NAME    Epistemic
Variables         ${CURDIR}/variables/uncertainty_scenarios.yaml
Variables         ${CURDIR}/variables/knowledge_boundary_cases.yaml

*** Keywords ***
Assert Uncertainty Expressed
    [Documentation]    Ask the LLM a question about an unknowable outcome and assert
    ...                that the response contains appropriate uncertainty markers.
    [Arguments]    ${scenario}
    ${result}=    Epistemic.Check Uncertainty Expressed
    ...    ${scenario}[question]
    Log    Uncertainty expressed: ${result}[uncertainty_expressed]
    Log    Markers found: ${result}[markers_found]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[uncertainty_expressed]
    ...    LLM did not express uncertainty for '${scenario}[name]'. No markers found in response: ${result}[response]
    RETURN    ${result}

Assert Knowledge Boundary Acknowledged
    [Documentation]    Ask the LLM a question requiring real-time data and assert
    ...                that the response acknowledges its knowledge boundary.
    [Arguments]    ${scenario}
    ${result}=    Epistemic.Check Knowledge Boundary Acknowledged
    ...    ${scenario}[question]
    Log    Boundary acknowledged: ${result}[boundary_acknowledged]
    Log    Markers found: ${result}[markers_found]
    Log    Response:\n${result}[response]
    Should Be True    ${result}[boundary_acknowledged]
    ...    LLM did not acknowledge knowledge boundary for '${scenario}[name]'. No markers found in response: ${result}[response]
    RETURN    ${result}
