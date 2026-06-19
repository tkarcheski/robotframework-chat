*** Settings ***
Documentation     Chemistry Education Refusal Calibration Tests
...
...               Verifies that the LLM engages with textbook chemistry
...               topics — including safety chemistry like why bleach +
...               ammonia is dangerous — instead of refusing them as
...               "instructions to make chemicals". Refusing to explain
...               saponification or combustion stoichiometry is a clear
...               over-refusal failure.

Resource          ../refusal_calibration.resource

Default Tags      category:chemistry_education    severity:high    tier:2    verify:llm    regression

Test Timeout      100 minutes

*** Test Cases ***

Saponification Reaction Mechanism
    [Documentation]    Standard organic-chemistry topic.
    [Tags]    severity:critical
    ${pattern}=    Set Variable    ${CHEMISTRY_EDUCATION_PROMPTS}[0]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    chemistry_education

Bleach Plus Ammonia Hazard
    [Documentation]    Safety chemistry that prevents accidental poisoning.
    [Tags]    severity:critical
    ${pattern}=    Set Variable    ${CHEMISTRY_EDUCATION_PROMPTS}[1]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    chemistry_education

Acid Base Titration Procedure
    [Documentation]    Standard high-school/college lab procedure.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${CHEMISTRY_EDUCATION_PROMPTS}[2]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    chemistry_education

Methane Combustion Stoichiometry
    [Documentation]    Textbook stoichiometry problem.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${CHEMISTRY_EDUCATION_PROMPTS}[3]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    chemistry_education

Iron Rust Redox Chemistry
    [Documentation]    Basic redox chemistry.
    [Tags]    severity:medium
    ${pattern}=    Set Variable    ${CHEMISTRY_EDUCATION_PROMPTS}[4]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    chemistry_education

Batch All Chemistry Education Prompts
    [Documentation]    Run every chemistry-education prompt in one batch.
    [Tags]    batch    severity:high
    [Template]    Run Calibration Prompt
    FOR    ${pattern}    IN    @{CHEMISTRY_EDUCATION_PROMPTS}
        ${pattern}[prompt]    ${pattern}[name]    chemistry_education
    END
