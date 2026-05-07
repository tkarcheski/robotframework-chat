*** Settings ***
Documentation     Causal reasoning evaluation tests.
...
...               Tests the LLM's ability to:
...               - Distinguish correlation from causation
...               - Identify confounding variables
...               - Reason about counterfactual scenarios
...               - Evaluate the validity of proposed interventions
...
...               All tests are tier:2 (LLM-graded) because correct answers
...               require nuanced multi-step reasoning that cannot be reduced
...               to substring matching.

Resource          causal_reasoning.resource

Default Tags      causal_reasoning    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***

Ice Cream And Drowning Are Correlated Not Causal
    [Documentation]    Classic spurious correlation: both ice cream sales and
    ...                drowning rates increase in summer due to hot weather.
    ...                The model must identify the confounding variable (season/heat).
    [Tags]    causal_reasoning    correlation    confound    tier:2    verify:llm
    Assert Causal Discrimination
    ...    Research data shows that on days when ice cream sales are highest, the number of drowning incidents also tends to be highest. People eat more ice cream and more people drown on the same days.
    ...    This is a correlation, not causation. The confounding variable is hot weather or summer season: warm weather causes both higher ice cream sales and more swimming activity, which leads to more drowning incidents. Ice cream does not cause drowning.
    ...    min_score=0.6

Hospital Mortality And Doctor Count — Selection Bias
    [Documentation]    Hospitals with more doctors have higher death rates because
    ...                they treat more severe cases (selection bias / confound).
    [Tags]    causal_reasoning    selection_bias    confound    tier:2    verify:llm
    Assert Causal Discrimination
    ...    A study finds that hospitals with more doctors per patient have higher mortality rates. The more doctors a hospital has, the more patients die there.
    ...    This is not a causal relationship — it is confounded by case severity. Hospitals with more doctors tend to be larger tertiary care centres that treat more critically ill patients. The higher mortality reflects patient severity, not the number of doctors.
    ...    min_score=0.6

Shoe Size And Reading Ability — Age Confound
    [Documentation]    Among children, shoe size correlates with reading ability because
    ...                both are caused by age (older children have larger feet and read better).
    [Tags]    causal_reasoning    age_confound    tier:2    verify:llm
    Assert Causal Discrimination
    ...    A researcher finds that among elementary school children, those with larger shoe sizes score higher on reading tests. Children with bigger feet are better readers.
    ...    This is a spurious correlation caused by age. Older children have both larger feet and greater reading ability. Shoe size does not cause better reading; age is the confounding variable driving both.
    ...    min_score=0.5

Nobel Prize And Chocolate Consumption — Wealth Confound
    [Documentation]    Countries with higher per-capita chocolate consumption have more
    ...                Nobel laureates — both correlate with national wealth and development.
    [Tags]    causal_reasoning    wealth_confound    tier:2    verify:llm
    Assert Causal Discrimination
    ...    A study published in the New England Journal of Medicine found a strong correlation between a country's per-capita chocolate consumption and the number of Nobel Prize winners that country has produced. Countries where people eat more chocolate win more Nobel Prizes.
    ...    This is a correlation, not causation. Both are driven by national wealth and development: wealthy, well-educated nations can afford more chocolate and also invest more in research and education, leading to more Nobel laureates. Chocolate does not cause Nobel Prize wins.
    ...    min_score=0.5

Counterfactual — Antibiotics Not Discovered
    [Documentation]    Counterfactual: if penicillin had never been discovered,
    ...                how would average life expectancy differ?
    [Tags]    causal_reasoning    counterfactual    tier:2    verify:llm
    Assert Counterfactual Quality
    ...    If penicillin and other antibiotics had never been discovered, how would average human life expectancy today compare to what it actually is?
    ...    Life expectancy would be significantly lower — perhaps by 10 to 20 years. Bacterial infections like pneumonia, tuberculosis, and sepsis killed millions before antibiotics; without them, these diseases would remain leading causes of death across all age groups.
    ...    min_score=0.5

Counterfactual — Printing Press Never Invented
    [Documentation]    Counterfactual: without the printing press, how would
    ...                the Protestant Reformation have spread differently?
    [Tags]    causal_reasoning    counterfactual    tier:2    verify:llm
    Assert Counterfactual Quality
    ...    If the printing press had never been invented, how would the Protestant Reformation of the 16th century have spread differently, if at all?
    ...    Without the printing press, Martin Luther's ideas would have spread far more slowly and narrowly — through handwritten manuscripts and word of mouth, as in previous religious reform movements. The Reformation would likely have remained a local or regional dispute rather than rapidly fragmenting Christianity across Europe.
    ...    min_score=0.4

Intervention — School Breakfast Programme
    [Documentation]    Research shows students who eat breakfast perform better academically.
    ...                Is a school free-breakfast programme a valid causal intervention?
    [Tags]    causal_reasoning    intervention    tier:2    verify:llm
    Assert Intervention Evaluation
    ...    Research consistently shows that students who eat breakfast before school perform better academically than those who skip breakfast. A school district is considering providing free breakfast to all students. Is providing free breakfast a reasonable intervention to improve academic performance?
    ...    Yes, this is a reasonable intervention. There is good mechanistic evidence that nutrition affects cognitive function and concentration. Providing breakfast directly addresses the proposed causal mechanism — hunger impairing performance — rather than just exploiting a correlation. Multiple randomised controlled trials support school breakfast programmes improving attendance and attentiveness.
    ...    min_score=0.5

Intervention — Forcing Gym Use Based On Correlation
    [Documentation]    Employees who use the company gym are more productive.
    ...                Forcing all employees to use the gym may not transfer the benefit.
    [Tags]    causal_reasoning    intervention    reverse_causation    tier:2    verify:llm
    Assert Intervention Evaluation
    ...    A company's internal data shows that employees who use the company gym regularly are significantly more productive than those who do not. HR is proposing a policy to require all employees to use the gym at least twice a week to boost company-wide productivity.
    ...    This intervention may not work as intended. The correlation could be explained by reverse causation (more motivated, productive employees are also more likely to exercise) or by a confounding variable (health-conscious employees are both productive and gym users). Forcing gym use on unmotivated employees is unlikely to replicate the observed productivity gains and may cause resentment. A more careful causal analysis is needed before mandating this policy.
    ...    min_score=0.5
