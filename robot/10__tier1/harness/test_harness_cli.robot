*** Settings ***
Documentation     End-to-end tests for the ``rfc harness start|status|end``
...               session-bracketing CLI (Issue #429, merged PR #408).
...
...               Every CLI invocation is a separate OS process sharing only
...               the workspace's git sidecar and sqlite database, so these
...               tests verify the real cross-process contract — including
...               ``makefile_session_id()`` attachment (Issue #411) and the
...               force-overwrite orphaned-row regression (Issue #412).
...               No LLM is invoked; assertions are pure Python.

Library           rfc.harness_cli_kw.HarnessCliRunner    WITH NAME    Harness

Test Setup        Create Workspace
Test Teardown     Remove Workspace

Test Tags         harness-cli    tier:1    verify:python    axis:harness

*** Keywords ***
Create Workspace
    ${root}=    Evaluate    tempfile.mkdtemp(prefix="harness-cli-")    modules=tempfile
    ${ws}=    Harness.Create Harness Workspace    ${root}
    Set Test Variable    ${WS}    ${ws}

Remove Workspace
    Evaluate    shutil.rmtree($WS["path"], ignore_errors=True)    modules=shutil

Start Session
    [Documentation]    Run ``rfc harness start`` and return the new session id.
    ${result}=    Harness.Run Harness Command    ${WS}    start    --tool    claude-code
    Should Be Equal As Integers    ${result}[rc]    0
    ${session_id}=    Harness.Get Sidecar Session Id    ${WS}
    RETURN    ${session_id}

*** Test Cases ***
Start Writes Sidecar And Open DB Row
    [Documentation]    ``start`` creates the sidecar and an agentic_harnesses
    ...                row that is still open (no ended_at / outcome).
    ${session_id}=    Start Session
    ${row}=    Harness.Get Harness Row    ${WS}    ${session_id}
    Should Be Equal    ${row}[session_id]    ${session_id}
    Should Be Equal    ${row}[tool_name]     claude-code
    Should Not Be Empty    ${row}[started_at]
    Should Be Empty    ${row}[ended_at]
    Should Be Empty    ${row}[outcome]

Sidecar Survives Across Processes
    [Documentation]    ``status`` in a fresh process reads the sidecar written
    ...                by ``start`` in an earlier process.
    ${session_id}=    Start Session
    ${status}=    Harness.Run Harness Command    ${WS}    status
    Should Be Equal As Integers    ${status}[rc]    0
    Should Contain    ${status}[stdout]    active session ${session_id}

End Closes Session And Removes Sidecar
    [Documentation]    ``end`` sets ended_at + outcome on the DB row and
    ...                deletes the sidecar; ``status`` then reports no session.
    ${session_id}=    Start Session
    ${end}=    Harness.Run Harness Command    ${WS}    end    --outcome    success
    Should Be Equal As Integers    ${end}[rc]    0
    Harness.Sidecar Should Not Exist    ${WS}
    ${row}=    Harness.Get Harness Row    ${WS}    ${session_id}
    Should Not Be Empty    ${row}[ended_at]
    Should Be Equal    ${row}[outcome]    success
    ${status}=    Harness.Run Harness Command    ${WS}    status
    Should Be Equal As Integers    ${status}[rc]    0
    Should Contain    ${status}[stdout]    no active session

Duplicate Start Without Force Is Rejected
    [Documentation]    A second ``start`` while a session is active fails and
    ...                leaves the original session untouched.
    ${session_id}=    Start Session
    ${second}=    Harness.Run Harness Command    ${WS}    start    --tool    claude-code
    Should Be Equal As Integers    ${second}[rc]    1
    Should Contain    ${second}[stderr]    active session already recorded
    ${unchanged}=    Harness.Get Sidecar Session Id    ${WS}
    Should Be Equal    ${unchanged}    ${session_id}

Force Overwrite Closes Previous Row
    [Documentation]    Issue #412 regression: ``start --force-overwrite`` must
    ...                not orphan the previous "running" row — it is closed
    ...                with outcome=abandoned.
    ${first_id}=    Start Session
    ${forced}=    Harness.Run Harness Command    ${WS}    start    --tool    claude-code    --force-overwrite
    Should Be Equal As Integers    ${forced}[rc]    0
    ${second_id}=    Harness.Get Sidecar Session Id    ${WS}
    Should Not Be Equal    ${second_id}    ${first_id}
    ${old_row}=    Harness.Get Harness Row    ${WS}    ${first_id}
    Should Be Equal    ${old_row}[outcome]    abandoned
    Should Not Be Empty    ${old_row}[ended_at]
    ${new_row}=    Harness.Get Harness Row    ${WS}    ${second_id}
    Should Be Empty    ${new_row}[ended_at]

Status And End With No Active Session
    [Documentation]    Without a sidecar, ``status`` succeeds with a clear
    ...                message and ``end`` fails safely.
    ${status}=    Harness.Run Harness Command    ${WS}    status
    Should Be Equal As Integers    ${status}[rc]    0
    Should Contain    ${status}[stdout]    no active session
    ${end}=    Harness.Run Harness Command    ${WS}    end
    Should Be Equal As Integers    ${end}[rc]    1
    Should Contain    ${end}[stderr]    no active session

Makefile Session Id Tracks Active Session
    [Documentation]    Issue #411 contract: while a session is active,
    ...                ``makefile_session_id()`` (fresh process, like the
    ...                Makefile) returns the sidecar id; after ``end`` it
    ...                returns a fresh UUID per invocation.
    ${session_id}=    Start Session
    ${active}=    Harness.Get Makefile Session Id    ${WS}
    Should Be Equal    ${active}    ${session_id}
    ${end}=    Harness.Run Harness Command    ${WS}    end
    Should Be Equal As Integers    ${end}[rc]    0
    ${first}=    Harness.Get Makefile Session Id    ${WS}
    ${second}=    Harness.Get Makefile Session Id    ${WS}
    Should Not Be Equal    ${first}    ${session_id}
    Should Not Be Equal    ${first}    ${second}
