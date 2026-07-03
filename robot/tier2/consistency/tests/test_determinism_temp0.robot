*** Settings ***
Documentation     Determinism Tests — Temperature 0 Stability
...
...               Replays each prompt N_RUNS times at temperature=0 and asserts
...               every response is byte-identical. Catches:
...                 * non-deterministic kernels in the serving stack
...                 * quantization-induced randomness artifacts
...                 * silent model swaps mid-suite
...
...               Tier 1 / verify:python — pure Python string-equality check.

Resource          ../consistency.resource

Test Tags         consistency    determinism    tier:1    verify:python

Test Timeout      250 minutes


*** Test Cases ***
Capital Of France Is Deterministic At Temp Zero
    [Documentation]    Single-word factual answer must repeat exactly.
    [Tags]    factual    severity:high    regression
    Run Determinism Check    ${DETERMINISM_PROMPTS}[0]

Multiplication Is Deterministic At Temp Zero
    [Documentation]    Arithmetic answer must repeat exactly across runs.
    [Tags]    math    severity:high    regression
    Run Determinism Check    ${DETERMINISM_PROMPTS}[1]

String Reversal Is Deterministic At Temp Zero
    [Documentation]    Token-level transformation must repeat exactly.
    [Tags]    string_op    severity:medium    regression
    Run Determinism Check    ${DETERMINISM_PROMPTS}[2]

Power Computation Is Deterministic At Temp Zero
    [Documentation]    Power-of-two answer must repeat exactly.
    [Tags]    math    severity:medium    regression
    Run Determinism Check    ${DETERMINISM_PROMPTS}[3]

Uppercase Spelling Is Deterministic At Temp Zero
    [Documentation]    Case transformation must repeat exactly.
    [Tags]    string_op    severity:medium    regression
    Run Determinism Check    ${DETERMINISM_PROMPTS}[4]
