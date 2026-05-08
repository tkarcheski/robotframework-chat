*** Settings ***
Documentation     Shared keywords for causal reasoning tests.
...               Provides reusable keywords for cause identification,
...               effect prediction, counterfactual reasoning,
...               correlation vs. causation, and causal chain tests.

Library           rfc.causal_reasoning_keywords.CausalReasoningKeywords    WITH NAME    Causal
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Keywords ***
Ask And Assert Cause Identification
    [Documentation]    Ask LLM to identify the root cause and assert score >= threshold.
    [Arguments]    ${scenario}    ${question}    ${expected}    ${threshold}=0.5
    ${result}=    Causal.Ask And Assert Causal Reasoning
    ...    scenario=${scenario}
    ...    question=${question}
    ...    expected=${expected}
    ...    question_type=cause_id
    ...    threshold=${threshold}
    RETURN    ${result}

Ask And Assert Effect Prediction
    [Documentation]    Ask LLM to predict an effect and assert score >= threshold.
    [Arguments]    ${scenario}    ${question}    ${expected}    ${threshold}=0.5
    ${result}=    Causal.Ask And Assert Causal Reasoning
    ...    scenario=${scenario}
    ...    question=${question}
    ...    expected=${expected}
    ...    question_type=effect_pred
    ...    threshold=${threshold}
    RETURN    ${result}

Ask And Assert Counterfactual
    [Documentation]    Ask LLM to reason counterfactually and assert score >= threshold.
    [Arguments]    ${scenario}    ${question}    ${expected}    ${threshold}=0.5
    ${result}=    Causal.Ask And Assert Causal Reasoning
    ...    scenario=${scenario}
    ...    question=${question}
    ...    expected=${expected}
    ...    question_type=counterfactual
    ...    threshold=${threshold}
    RETURN    ${result}

Ask And Assert Correlation Vs Causation
    [Documentation]    Ask LLM to distinguish correlation from causation and assert score >= threshold.
    [Arguments]    ${scenario}    ${question}    ${expected}    ${threshold}=0.5
    ${result}=    Causal.Ask And Assert Causal Reasoning
    ...    scenario=${scenario}
    ...    question=${question}
    ...    expected=${expected}
    ...    question_type=correlation_vs_causation
    ...    threshold=${threshold}
    RETURN    ${result}

Ask And Assert Causal Chain
    [Documentation]    Ask LLM to trace a multi-hop causal chain and assert score >= threshold.
    [Arguments]    ${scenario}    ${question}    ${expected}    ${threshold}=0.5
    ${result}=    Causal.Ask And Assert Causal Reasoning
    ...    scenario=${scenario}
    ...    question=${question}
    ...    expected=${expected}
    ...    question_type=causal_chain
    ...    threshold=${threshold}
    RETURN    ${result}

Assert Causal JSON Valid
    [Documentation]    Ask LLM for structured causal JSON and assert structure is valid.
    [Arguments]    ${prompt}
    ${check}=    Causal.Ask And Check Causal Json Structure    ${prompt}
    Should Be True    ${check}[is_valid]
    ...    Structured causal JSON invalid: cause=${check}[cause], effect=${check}[effect]
    RETURN    ${check}
