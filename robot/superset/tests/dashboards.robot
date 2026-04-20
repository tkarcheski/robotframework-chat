*** Settings ***
Documentation     Browser-based Superset dashboard evaluation.
...               Logs into Superset, visits each dashboard, converts the page
...               to markdown, and asks the LLM to evaluate data quality and
...               suggest improvements.
Library           Browser    WITH NAME    Playwright
Library           rfc.browser_keywords.BrowserKeywords    WITH NAME    Page
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           String
Library           OperatingSystem

Suite Setup       Open Superset And Login
Suite Teardown    Close Browser

*** Variables ***
${SUPERSET_URL}         http://ai1:8088
${SUPERSET_USER}        admin
${SUPERSET_PASSWORD}    changeme
${DASHBOARD_IDS}        11,12,13,14,15,16

*** Test Cases ***
Superset Login Page Loads
    [Documentation]    Can the browser reach the Superset login page?
    [Tags]    tier:0    verify:robot    superset
    Get Title    contains    Superset

All Dashboards Load Successfully
    [Documentation]    Do all configured dashboards render without HTTP errors?
    [Tags]    tier:0    verify:robot    superset
    @{ids}=    Split String    ${DASHBOARD_IDS}    ,
    FOR    ${id}    IN    @{ids}
        Go To    ${SUPERSET_URL}/superset/dashboard/${id}/
        Wait For Load State    networkidle    timeout=30s
        ${title}=    Get Title
        Should Not Contain    ${title}    404
        Should Not Contain    ${title}    Error
        Log    Dashboard ${id}: ${title}
    END

LLM Evaluates Model Performance Dashboard
    [Documentation]    Does the Model Performance dashboard contain meaningful data?
    [Tags]    tier:2    verify:llm    superset    dashboard:model-performance
    ${feedback}=    Evaluate Dashboard    14    Model Performance
    Should Not Contain    ${feedback}    empty
    Log    LLM Feedback: ${feedback}

LLM Evaluates RFC Test Health Dashboard
    [Documentation]    Does the RFC Test Health dashboard show actionable test metrics?
    [Tags]    tier:2    verify:llm    superset    dashboard:test-health
    ${feedback}=    Evaluate Dashboard    15    RFC Test Health
    Log    LLM Feedback: ${feedback}

LLM Evaluates Test Results Dashboard
    [Documentation]    Does the Test Results dashboard display recent test data?
    [Tags]    tier:2    verify:llm    superset    dashboard:test-results
    ${feedback}=    Evaluate Dashboard    13    Test Results
    Log    LLM Feedback: ${feedback}

LLM Evaluates Test Infrastructure Dashboard
    [Documentation]    Does the Test Infrastructure dashboard show healthy infra?
    [Tags]    tier:2    verify:llm    superset    dashboard:test-infra
    ${feedback}=    Evaluate Dashboard    16    Test Infrastructure
    Log    LLM Feedback: ${feedback}

LLM Evaluates Host Metrics Dashboard
    [Documentation]    Does the Host Metrics dashboard show current node data?
    [Tags]    tier:2    verify:llm    superset    dashboard:host-metrics
    ${feedback}=    Evaluate Dashboard    11    Host Metrics
    Log    LLM Feedback: ${feedback}

LLM Evaluates Model Details Dashboard
    [Documentation]    Does the Model Details dashboard provide useful model info?
    [Tags]    tier:2    verify:llm    superset    dashboard:model-details
    ${feedback}=    Evaluate Dashboard    12    Model Details
    Log    LLM Feedback: ${feedback}

*** Keywords ***
Open Superset And Login
    [Documentation]    Launch browser, navigate to Superset, and authenticate.
    New Browser    chromium    headless=true
    New Page    ${SUPERSET_URL}/login/
    Wait For Load State    networkidle    timeout=30s
    Fill Text    id=username    ${SUPERSET_USER}
    Fill Text    id=password    ${SUPERSET_PASSWORD}
    Click    input[type="submit"]
    Wait For Load State    networkidle    timeout=15s

Evaluate Dashboard
    [Documentation]    Navigate to a dashboard, convert to markdown, ask LLM to evaluate.
    [Arguments]    ${dashboard_id}    ${dashboard_name}
    Go To    ${SUPERSET_URL}/superset/dashboard/${dashboard_id}/
    Wait For Load State    networkidle    timeout=30s
    ${html}=    Get Page Source
    ${markdown}=    Page.Convert HTML To Markdown    ${html}
    Log    Markdown for ${dashboard_name}:\n${markdown}    level=DEBUG
    ${prompt}=    Page.Build Evaluation Prompt
    ...    ${markdown}
    ...    page_type=dashboard
    ...    context=Dashboard: ${dashboard_name}. This is part of the robotframework-chat LLM benchmarking system. Dashboards visualize test results from Robot Framework test suites running against Ollama models.
    ${feedback}=    LLM.Ask LLM    ${prompt}
    RETURN    ${feedback}
