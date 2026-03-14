*** Settings ***
Documentation     Test PostgreSQL connectivity and push host info.
Library           rfc.superset_keywords.SupersetKeywords    WITH NAME    Superset


*** Test Cases ***
Database Connection Is Alive
    [Documentation]    Verify that DATABASE_URL connects to PostgreSQL.
    ${url}=    Superset.Get Database URL
    Log    DATABASE_URL: ${url}
    Should Not Be Equal    ${url}    NOT SET
    ...    DATABASE_URL is not configured. Set it in .env.
    ${version}=    Superset.Connect To Database
    Should Contain    ${version}    PostgreSQL
    Log    Connected: ${version}

Host Info Is Pushed
    [Documentation]    Collect local hardware info and upsert into host_info table.
    ${info}=    Superset.Push Host Info
    Should Not Be Empty    ${info}[hostname]
    Log    Registered host: ${info}[hostname]
    Log    OS: ${info}[os_name] ${info}[os_version]
    Log    CPU: ${info}[cpu_arch] x${info}[cpu_count]
    Log    RAM: ${info}[total_ram_gb] GB

All Hosts Are Visible
    [Documentation]    Verify at least one host is registered in the database.
    ${hosts}=    Superset.Get All Hosts
    ${count}=    Get Length    ${hosts}
    Should Be True    ${count} >= 1
    ...    No hosts registered. Push Host Info should have created one.
    FOR    ${host}    IN    @{hosts}
        Log    Host: ${host}[hostname] — last seen: ${host}[last_seen]
    END

Core Tables Have Data
    [Documentation]    Verify that key RFC tables exist and contain rows.
    ${counts}=    Superset.Get Table Row Counts
    Log    Table row counts: ${counts}
    # These tables should exist (row count >= 0 means table exists).
    # A count of -1 means the query failed (table missing).
    Should Be True    ${counts}[test_runs] >= 0
    ...    test_runs table is missing or inaccessible.
    Should Be True    ${counts}[test_results] >= 0
    ...    test_results table is missing or inaccessible.
    Should Be True    ${counts}[host_info] >= 1
    ...    host_info should have at least 1 row after Push Host Info.
