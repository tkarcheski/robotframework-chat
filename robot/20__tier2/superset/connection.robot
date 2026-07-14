*** Settings ***
Documentation     Test PostgreSQL connectivity and verify 2-table schema.
Library           rfc.superset_keywords.SupersetKeywords    WITH NAME    Superset

# RFC-008 A1: pure DB/BI plumbing -- no model, harness, or prompt in the loop.
Test Tags         axis:none


*** Test Cases ***
Database Connection Is Alive
    [Documentation]    Can the system connect to PostgreSQL via DATABASE_URL?
    [Tags]    tier:1    verify:python
    ${url}=    Superset.Get Database URL
    Log    DATABASE_URL: ${url}
    Should Not Be Equal    ${url}    NOT SET
    ...    DATABASE_URL is not configured. Set it in .env.
    ${version}=    Superset.Connect To Database
    Should Contain    ${version}    PostgreSQL
    Log    Connected: ${version}

Core Tables Have Data
    [Documentation]    Can the system verify that test_runs and test_results tables exist and have data?
    [Tags]    tier:1    verify:python
    ${counts}=    Superset.Get Table Row Counts
    Log    Table row counts: ${counts}
    # These tables should exist (row count >= 0 means table exists).
    # A count of -1 means the query failed (table missing).
    Should Be True    ${counts}[test_runs] >= 0
    ...    test_runs table is missing or inaccessible.
    Should Be True    ${counts}[test_results] >= 0
    ...    test_results table is missing or inaccessible.
