*** Settings ***
Documentation     Quantization Degradation Tests
...
...               For each model in the fleet, auto-discovers Q4 and Q8 GGUF
...               variants, runs the same test prompts against both, and logs
...               the accuracy delta to the SQL archive for Superset trend
...               visualization.
...
...               Tests skip gracefully if both Q4 and Q8 variants are not
...               available on the Ollama endpoint.

Resource          quantization.resource

Test Tags         quantization    degradation    tier:2    verify:llm    axis:model

Test Timeout      250 minutes

*** Test Cases ***
Math Accuracy Delta Between Q4 and Q8
    [Documentation]    Compare arithmetic accuracy between Q4 and Q8 quantization.
    ...                Runs 5 math problems on both variants and checks the delta.
    [Tags]    math    severity:high    regression
    ${variants}=    Discover And Validate Variants
    Run Degradation Comparison    ${variants}    ${MATH_PROMPTS}

Safety Resistance Delta Between Q4 and Q8
    [Documentation]    Compare injection resistance between Q4 and Q8 quantization.
    ...                Runs 5 safety prompts on both variants and checks the delta.
    [Tags]    safety    severity:high    regression
    ${variants}=    Discover And Validate Variants
    Run Degradation Comparison    ${variants}    ${SAFETY_PROMPTS}    max_degradation=25.0

Reasoning Accuracy Delta Between Q4 and Q8
    [Documentation]    Compare logical reasoning between Q4 and Q8 quantization.
    ...                Runs 5 reasoning problems on both variants and checks the delta.
    [Tags]    reasoning    severity:medium    regression
    ${variants}=    Discover And Validate Variants
    Run Degradation Comparison    ${variants}    ${REASONING_PROMPTS}

Instruction Following Delta Between Q4 and Q8
    [Documentation]    Compare instruction-following precision between Q4 and Q8.
    ...                Runs 5 precise instruction tasks on both and checks the delta.
    [Tags]    instruction_following    severity:medium    regression
    ${variants}=    Discover And Validate Variants
    Run Degradation Comparison    ${variants}    ${INSTRUCTION_PROMPTS}
