*** Settings ***
Documentation     Demographic Parity Bias Tests
...
...               Tests whether the LLM produces substantively equivalent responses
...               to identical professional scenarios when only demographic markers
...               (names, locations, age, gender) are changed.
...
...               == Test Categories ==
...
...               Hiring (hiring):
...               - Name-based bias across gender and ethnicity
...
...               Financial (financial):
...               - Location-based bias across socioeconomic signals
...
...               Medical (medical):
...               - Age and gender bias in clinical recommendations
...
...               Performance (performance):
...               - Gendered language bias in performance reviews

Resource          bias.resource

Suite Setup       Setup Bias Test Environment
Suite Teardown    Cleanup Bias Tests

Default Tags      bias    demographic_parity    tier:2    verify:llm

Test Timeout      5 minutes

*** Test Cases ***

Hiring Recommendation - Name Bias Across Gender And Ethnicity
    [Documentation]    Do hiring recommendations change based on culturally-coded names?
    ...                Same qualifications, different names spanning gender and ethnicity.
    [Tags]    hiring    severity:high
    ${scenario}=    Set Variable    ${HIRING_SCENARIOS}[0]
    Run Parity Test Case    ${scenario}

Hiring Recommendation - Marketing Director Name Bias
    [Documentation]    Does advancing a candidate to final round depend on name?
    [Tags]    hiring    severity:high
    ${scenario}=    Set Variable    ${HIRING_SCENARIOS}[1]
    Run Parity Test Case    ${scenario}

Financial Advice - Location Bias In Investment Strategy
    [Documentation]    Does investment advice change based on client location?
    ...                Same financial profile, different geographic/socioeconomic markers.
    [Tags]    financial    severity:high
    ${scenario}=    Set Variable    ${FINANCIAL_SCENARIOS}[0]
    Run Parity Test Case    ${scenario}

Financial Advice - Retirement Planning Location Bias
    [Documentation]    Does retirement planning advice differ by client location?
    [Tags]    financial    severity:medium
    ${scenario}=    Set Variable    ${FINANCIAL_SCENARIOS}[1]
    Run Parity Test Case    ${scenario}

Medical Triage - Age And Gender Bias In Chest Pain Assessment
    [Documentation]    Are chest pain symptoms triaged with equal urgency across age/gender?
    ...                Same symptoms, different patient demographics.
    [Tags]    medical    severity:critical
    ${scenario}=    Set Variable    ${MEDICAL_SCENARIOS}[0]
    Run Parity Test Case    ${scenario}

Medical Triage - Mental Health Assessment Bias
    [Documentation]    Does mental health assessment approach vary by patient demographics?
    [Tags]    medical    severity:high
    ${scenario}=    Set Variable    ${MEDICAL_SCENARIOS}[1]
    Run Parity Test Case    ${scenario}

Performance Review - Gendered Language In Sales Assessment
    [Documentation]    Does a performance summary use different language based on gender?
    ...                Same achievements, different names and pronouns.
    [Tags]    performance    severity:high
    ${scenario}=    Set Variable    ${PERFORMANCE_SCENARIOS}[0]
    Run Parity Test Case    ${scenario}

Performance Review - Leadership Assessment Gender Bias
    [Documentation]    Does leadership language differ by gender for identical accomplishments?
    [Tags]    performance    severity:high
    ${scenario}=    Set Variable    ${PERFORMANCE_SCENARIOS}[1]
    Run Parity Test Case    ${scenario}

Batch Hiring Parity Tests
    [Documentation]    Run all hiring scenarios as a batch
    [Tags]    hiring    batch
    Run Parity Test Batch    ${HIRING_SCENARIOS}

Batch Financial Parity Tests
    [Documentation]    Run all financial scenarios as a batch
    [Tags]    financial    batch
    Run Parity Test Batch    ${FINANCIAL_SCENARIOS}

Batch Medical Parity Tests
    [Documentation]    Run all medical scenarios as a batch
    [Tags]    medical    batch
    Run Parity Test Batch    ${MEDICAL_SCENARIOS}

Batch Performance Parity Tests
    [Documentation]    Run all performance review scenarios as a batch
    [Tags]    performance    batch
    Run Parity Test Batch    ${PERFORMANCE_SCENARIOS}
