*** Settings ***
Documentation     End-to-end coverage for the #409 dialog recorder (#437).
...
...               Spawns a child robot run of
...               robot/tier1/dialog/fixtures/record_dialog_fixture.robot with
...               rfc.dialog_listener.DialogListener attached — the exact
...               production wiring — then asserts via DATABASE_URL that
...               the recording and its turns landed in PostgreSQL:
...               1 dialog_recordings row, ended_at set, N FK-intact
...               dialog_turns rows with sequential turn numbers.
...
...               Skips (never fails) when DATABASE_URL is unset or the
...               database is unreachable, per the CLAUDE.md skip-and-log
...               policy. The DB-down test needs no live database at all:
...               it proves the listener's skip-and-log contract by
...               pointing it at a dead endpoint.

Library           rfc.dialog_e2e_keywords.DialogE2EKeywords    AS    DialogE2E

Test Tags         dialog    tier:1    verify:python

*** Variables ***
${FIXTURE_TURNS}      3
${DEAD_DB_URL}        postgresql://rfc:wrong@127.0.0.1:9/rfc_unreachable

*** Test Cases ***
Dialog Recording Persists End To End
    [Documentation]    Child robot run with DialogListener writes the
    ...    recording and all turns to the database at DATABASE_URL.
    # Init before any Skip If: Robot runs the teardown for skipped tests
    # too, and Cleanup Recording dereferences ${RECORDING_ID} (#461).
    ${RECORDING_ID}=    Set Variable    ${EMPTY}
    Set Test Variable    ${RECORDING_ID}
    ${db_url}=    Set Variable    %{DATABASE_URL=}
    Skip If    "${db_url}" == ""    DATABASE_URL not set — skipping live database e2e check
    ${reachable}=    DialogE2E.Dialog Database Reachable    ${db_url}
    Skip If    not ${reachable}    Database at DATABASE_URL is unreachable
    ${run}=    DialogE2E.Run Dialog Fixture Suite
    ...    ${OUTPUT DIR}${/}dialog_e2e_child    database_url=${db_url}
    Set Test Variable    ${RECORDING_ID}    ${run}[recording_id]
    Should Be Equal As Integers    ${run}[rc]    0
    ...    msg=fixture suite failed: ${run}[stdout]
    Should Not Be Empty    ${run}[recording_id]
    ...    msg=fixture did not report a recording id
    ${summary}=    DialogE2E.Assert Dialog Recording Persisted
    ...    ${db_url}    ${run}[recording_id]    ${FIXTURE_TURNS}
    Log    Persisted dialog verified: ${summary}
    [Teardown]    Cleanup Recording    ${db_url}

Dialog Listener Tolerates Database Down
    [Documentation]    With an unreachable database the listener logs a
    ...    warning and the recorded test still passes (skip-and-log).
    ${run}=    DialogE2E.Run Dialog Fixture Suite
    ...    ${OUTPUT DIR}${/}dialog_e2e_dbdown    database_url=${DEAD_DB_URL}
    Should Be Equal As Integers    ${run}[rc]    0
    ...    msg=DB-down must never fail the recorded test: ${run}[stdout]
    Should Be True    ${run}[warning_found]
    ...    msg=expected a DialogListener DB-failure warning in the child output

*** Keywords ***
Cleanup Recording
    [Documentation]    Remove the e2e recording so reruns stay deterministic.
    [Arguments]    ${db_url}
    IF    "${RECORDING_ID}" != ""
        DialogE2E.Delete Dialog Recording    ${db_url}    ${RECORDING_ID}
    END
