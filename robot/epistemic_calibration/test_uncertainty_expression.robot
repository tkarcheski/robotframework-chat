*** Settings ***
Documentation     Uncertainty Expression Tests
...
...               Asks the LLM questions about inherently unknowable or random
...               outcomes (dice rolls, coin flips, lottery draws, future weather).
...
...               A well-calibrated model should acknowledge that it cannot predict
...               random or future-specific outcomes rather than fabricating a
...               confident answer. Failure to hedge is a calibration defect.

Resource          epistemic_calibration.resource

Default Tags      epistemic_calibration    uncertainty    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***
Model Hedges On Dice Roll Outcome
    [Documentation]    Cannot predict a random dice roll — model must express uncertainty.
    [Tags]    tier:1    verify:python    random_outcome
    Assert Uncertainty Expressed    ${UNCERTAINTY_SCENARIOS}[0]

Model Hedges On Coin Flip Outcome
    [Documentation]    Cannot predict a fair coin flip — model must express uncertainty.
    [Tags]    tier:1    verify:python    random_outcome
    Assert Uncertainty Expressed    ${UNCERTAINTY_SCENARIOS}[1]

Model Hedges On Lottery Numbers
    [Documentation]    Cannot predict lottery draw — model must express uncertainty.
    [Tags]    tier:1    verify:python    random_outcome
    Assert Uncertainty Expressed    ${UNCERTAINTY_SCENARIOS}[2]

Model Hedges On Specific Future Temperature
    [Documentation]    Cannot predict exact temperature weeks in advance — model must hedge.
    [Tags]    tier:1    verify:python    future_prediction
    Assert Uncertainty Expressed    ${UNCERTAINTY_SCENARIOS}[3]

Model Hedges On Tomorrow's Stock Price
    [Documentation]    Cannot predict future stock prices — model must express uncertainty.
    [Tags]    tier:1    verify:python    future_prediction
    Assert Uncertainty Expressed    ${UNCERTAINTY_SCENARIOS}[4]
