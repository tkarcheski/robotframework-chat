*** Settings ***
Documentation     Correlation vs. Causation Tests
...
...               Asks the LLM to evaluate whether a stated causal claim is
...               genuinely causal or merely a spurious/confounded correlation.
...               Verdict is extracted deterministically from the first line of
...               the response, making these Tier 1 / verify:python tests.

Resource          causal_reasoning.resource

Default Tags      causal_reasoning    correlation    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Ice Cream And Drowning Are Not Causal
    [Documentation]    Summer heat confounds both ice cream sales and drowning — classic spurious correlation.
    [Tags]    tier:1    verify:python    spurious    confounding
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[0]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]

Shoe Size And Reading Ability Are Not Causal
    [Documentation]    Age confounds both shoe size and vocabulary in children.
    [Tags]    tier:1    verify:python    spurious    confounding
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[1]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]

TV Ownership And Life Expectancy Are Not Causal
    [Documentation]    Wealth confounds both TV ownership and healthcare access.
    [Tags]    tier:1    verify:python    spurious    confounding
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[2]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]

More Firefighters Does Not Cause More Damage
    [Documentation]    More firefighters are sent to bigger fires — reverse causation and selection bias.
    [Tags]    tier:1    verify:python    reverse_causation
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[3]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]

Pencil Ownership Does Not Cause Better Grades
    [Documentation]    Study habits and wealth confound pencil ownership and academic performance.
    [Tags]    tier:1    verify:python    spurious    confounding
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[4]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]

Smoking Causes Lung Cancer
    [Documentation]    Decades of RCT and epidemiological evidence establish direct causation.
    [Tags]    tier:1    verify:python    genuine_causation
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[5]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]

Exercise Reduces Cardiovascular Disease Risk
    [Documentation]    Multiple RCTs confirm exercise has a direct causal effect on heart health.
    [Tags]    tier:1    verify:python    genuine_causation
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[6]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]

Seat Belts Reduce Crash Fatality Risk
    [Documentation]    Mechanical causal mechanism — seat belts prevent ejection and collision impact.
    [Tags]    tier:1    verify:python    genuine_causation
    ${s}=    Set Variable    ${CORRELATION_SCENARIOS}[7]
    Assert Causal Verdict Correct    ${s}[scenario]    ${s}[claim]    ${s}[verdict]
