*** Settings ***
Documentation     Causal Chain and Effect Prediction Tests
...
...               Tests covering two complementary causal question types:
...
...               1. Causal chain tracing (causal_chain): given a multi-step
...                  A→B→C→D chain, identify the single initiating cause.
...                  Multi-hop chains are among the hardest causal tasks for
...                  small models.
...
...               2. Effect prediction (effect_pred): given an intervention,
...                  predict the downstream consequence(s). These test forward
...                  causal reasoning rather than backward attribution.
...
...               Grading: tier:2 (single LLM grader evaluates response).

Resource          causal_reasoning.resource
Variables         variables/causal_scenarios.yaml

Default Tags      causal_reasoning    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***
# --- Effect Prediction ---

Predict Effect Of Minimum Wage Above Equilibrium
    [Documentation]    Standard economic model predicts labour surplus (unemployment).
    [Tags]    tier:2    verify:llm    effect_pred    economics
    ${case}=    Set Variable    ${EFFECT_PRED_SCENARIOS}[0]
    Ask And Assert Effect Prediction
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Predict Effect Of Deforestation On Rainfall
    [Documentation]    Fewer trees → less evapotranspiration → reduced local rainfall.
    [Tags]    tier:2    verify:llm    effect_pred    environment    science
    ${case}=    Set Variable    ${EFFECT_PRED_SCENARIOS}[1]
    Ask And Assert Effect Prediction
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Predict Effect Of Central Bank Interest Rate Hike
    [Documentation]    Higher rates → reduced borrowing and investment.
    [Tags]    tier:2    verify:llm    effect_pred    economics    finance
    ${case}=    Set Variable    ${EFFECT_PRED_SCENARIOS}[2]
    Ask And Assert Effect Prediction
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Predict Effect Of Invasive Species On Food Web
    [Documentation]    Invasive fish competes with native fish; cascades up to osprey.
    [Tags]    tier:2    verify:llm    effect_pred    biology    environment
    ${case}=    Set Variable    ${EFFECT_PRED_SCENARIOS}[3]
    Ask And Assert Effect Prediction
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Predict Whether Vaccination Campaign Achieves Herd Immunity
    [Documentation]    80% coverage × 95% efficacy = 76% > 75% herd immunity threshold.
    [Tags]    tier:2    verify:llm    effect_pred    science    medicine
    ${case}=    Set Variable    ${EFFECT_PRED_SCENARIOS}[4]
    Ask And Assert Effect Prediction
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Predict Effect Of Chronic Sleep Deprivation
    [Documentation]    4h/night for 2 weeks causes cognitive and physiological degradation.
    [Tags]    tier:2    verify:llm    effect_pred    science    medicine
    ${case}=    Set Variable    ${EFFECT_PRED_SCENARIOS}[5]
    Ask And Assert Effect Prediction
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

# --- Causal Chain Tracing ---

Trace Chain From Deforestation To Village Flooding
    [Documentation]    5-step chain: deforestation → erosion → silting → shallow river → flooding.
    [Tags]    tier:2    verify:llm    causal_chain    environment    science
    ${case}=    Set Variable    ${CAUSAL_CHAIN_SCENARIOS}[0]
    Ask And Assert Causal Chain
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Trace Chain From Power Cut To Food Spoilage
    [Documentation]    5-step chain: power cut → fridge off → temperature rise → bacteria → spoilage.
    [Tags]    tier:2    verify:llm    causal_chain    everyday    science
    ${case}=    Set Variable    ${CAUSAL_CHAIN_SCENARIOS}[1]
    Ask And Assert Causal Chain
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Trace Chain From Distracted Driving To Bystander Injury
    [Documentation]    5-step chain: phone distraction → red light → swerve → parked car → bystander.
    [Tags]    tier:2    verify:llm    causal_chain    safety    everyday
    ${case}=    Set Variable    ${CAUSAL_CHAIN_SCENARIOS}[2]
    Ask And Assert Causal Chain
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Trace Chain From Smoking To Lung Cancer
    [Documentation]    5-step chain: smoking → DNA mutations → tumour-suppressor loss → uncontrolled growth → tumour.
    [Tags]    tier:2    verify:llm    causal_chain    science    medicine
    ${case}=    Set Variable    ${CAUSAL_CHAIN_SCENARIOS}[3]
    Ask And Assert Causal Chain
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Trace Chain From Energy Shock To Wage-Price Spiral
    [Documentation]    7-step chain: energy shock → cost-push inflation → wage demands → feedback loop.
    [Tags]    tier:2    verify:llm    causal_chain    economics    history
    ${case}=    Set Variable    ${CAUSAL_CHAIN_SCENARIOS}[4]
    Ask And Assert Causal Chain
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

Trace Chain From Software Bug To Database Corruption
    [Documentation]    5-step chain: bug → monitor crash → failover misfire → split-brain → data corruption.
    [Tags]    tier:2    verify:llm    causal_chain    software    engineering
    ${case}=    Set Variable    ${CAUSAL_CHAIN_SCENARIOS}[5]
    Ask And Assert Causal Chain
    ...    scenario=${case}[scenario]
    ...    question=${case}[question]
    ...    expected=${case}[expected]
    ...    threshold=${case}[threshold]

# --- Tier 1: Structured JSON Output ---

Structured Causal JSON For Engine Overheating
    [Documentation]    Tier 1: verify LLM outputs valid cause/effect JSON structure.
    [Tags]    tier:1    verify:python    causal_chain    everyday    engineering
    ${case}=    Set Variable    ${STRUCTURED_CAUSAL_PROMPTS}[0]
    Assert Causal JSON Valid    ${case}[prompt]

Structured Causal JSON For CO2 And Global Warming
    [Documentation]    Tier 1: verify LLM outputs valid cause/effect JSON for CO2 scenario.
    [Tags]    tier:1    verify:python    cause_id    science    environment
    ${case}=    Set Variable    ${STRUCTURED_CAUSAL_PROMPTS}[1]
    Assert Causal JSON Valid    ${case}[prompt]

Structured Causal JSON For Skipped Meals And Dizziness
    [Documentation]    Tier 1: verify LLM outputs valid cause/effect JSON for blood sugar scenario.
    [Tags]    tier:1    verify:python    cause_id    medicine    everyday
    ${case}=    Set Variable    ${STRUCTURED_CAUSAL_PROMPTS}[2]
    Assert Causal JSON Valid    ${case}[prompt]
