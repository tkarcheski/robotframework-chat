*** Settings ***
Documentation     Security vulnerability detection tests.
...
...               Presents the LLM with a code snippet containing a known
...               security vulnerability and a multiple-choice question (A–D).
...               The LLM must write the correct letter on the first line of
...               its response.  Graded deterministically — Tier 1 / verify:python.
...
...               Vulnerabilities covered: SQL injection, path traversal,
...               command injection, hardcoded secrets, insecure deserialisation.

Resource          code_review.resource

Default Tags      code_review    security    tier:1    verify:python
Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***

SQL Injection Via String Concatenation
    [Documentation]    Identify SQL injection risk from user input concatenated into a query string.
    [Tags]    tier:1    verify:python    security    sql_injection
    Assert Vulnerability Identified Correctly    ${SECURITY_SCENARIOS}[0]

Path Traversal Via User Controlled Filename
    [Documentation]    Identify path traversal risk when user input is used in a file path.
    [Tags]    tier:1    verify:python    security    path_traversal
    Assert Vulnerability Identified Correctly    ${SECURITY_SCENARIOS}[1]

Command Injection Via Shell True
    [Documentation]    Identify command injection when user input is interpolated with shell=True.
    [Tags]    tier:1    verify:python    security    command_injection
    Assert Vulnerability Identified Correctly    ${SECURITY_SCENARIOS}[2]

Hardcoded Secret In Source Code
    [Documentation]    Identify a hardcoded API key embedded directly in the source file.
    [Tags]    tier:1    verify:python    security    hardcoded_secret
    Assert Vulnerability Identified Correctly    ${SECURITY_SCENARIOS}[3]

Insecure Deserialization With Pickle
    [Documentation]    Identify arbitrary code execution risk from deserialising untrusted pickle data.
    [Tags]    tier:1    verify:python    security    deserialization
    Assert Vulnerability Identified Correctly    ${SECURITY_SCENARIOS}[4]
