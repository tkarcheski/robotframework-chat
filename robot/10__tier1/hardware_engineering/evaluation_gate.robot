*** Settings ***
Documentation     Offline regression gate over complete paired live run artifacts.
...               This only reports eligibility; it never trains or deploys models.
Library           rfc.hardware_eval_keywords.HardwareEvalKeywords    ${CURDIR}/fixtures
Test Tags         tier:1    verify:python    axis:model    hardware_gate

*** Variables ***
${BASELINE}       %{HW_BASELINE_RESULTS=}
${CANDIDATE}      %{HW_CANDIDATE_RESULTS=}
${PROFILE}        %{HW_GATE_PROFILE=}

*** Test Cases ***
Candidate Must Have Complete Comparable Nonregressing Evidence
    Skip If    not $BASELINE or not $CANDIDATE    Set HW_BASELINE_RESULTS and HW_CANDIDATE_RESULTS.
    ${gate}=    Compare Hardware Runs    ${BASELINE}    ${CANDIDATE}    ${PROFILE}
    Should Be Equal    ${gate}[verdict]    eligible    msg=${gate}
