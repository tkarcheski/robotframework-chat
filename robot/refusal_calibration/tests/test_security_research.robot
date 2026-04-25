*** Settings ***
Documentation     Security Research Refusal Calibration Tests
...
...               Verifies that the LLM engages with foundational
...               cybersecurity education (OSCP/CTF/OWASP topics) instead of
...               refusing them as "hacking instructions". These topics are
...               taught in CS curricula and are essential for defensive
...               security work.

Resource          ../refusal_calibration.resource

Default Tags      category:security_research    severity:critical    tier:2    verify:llm    regression

Test Timeout      2 minutes

*** Test Cases ***

SQL Injection Conceptual Explanation
    [Documentation]    Foundational web-security education for OSCP studies.
    [Tags]    severity:critical
    ${pattern}=    Set Variable    ${SECURITY_RESEARCH_PROMPTS}[0]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    security_research

XSS Type Differentiation
    [Documentation]    OWASP top-10 educational material.
    [Tags]    severity:critical
    ${pattern}=    Set Variable    ${SECURITY_RESEARCH_PROMPTS}[1]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    security_research

CSRF And SameSite Cookies
    [Documentation]    Standard web security concept.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${SECURITY_RESEARCH_PROMPTS}[2]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    security_research

Nmap SYN Scan In CTF Context
    [Documentation]    CTFs are sanctioned legal practice environments.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${SECURITY_RESEARCH_PROMPTS}[3]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    security_research

MD5 Weakness And Replacements
    [Documentation]    Defensive crypto guidance directly improves security.
    [Tags]    severity:critical
    ${pattern}=    Set Variable    ${SECURITY_RESEARCH_PROMPTS}[4]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    security_research

Stack Buffer Overflow Concept
    [Documentation]    Standard CS curriculum topic.
    [Tags]    severity:high
    ${pattern}=    Set Variable    ${SECURITY_RESEARCH_PROMPTS}[5]
    Run Calibration Prompt    ${pattern}[prompt]    ${pattern}[name]    security_research

Batch All Security Research Prompts
    [Documentation]    Run every security-research prompt in one batch.
    [Tags]    batch    severity:critical
    [Template]    Run Calibration Prompt
    FOR    ${pattern}    IN    @{SECURITY_RESEARCH_PROMPTS}
        ${pattern}[prompt]    ${pattern}[name]    security_research
    END
