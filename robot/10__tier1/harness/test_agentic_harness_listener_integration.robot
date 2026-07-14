*** Settings ***
Documentation     End-to-end integration tests for the AgenticHarnessListener
...               (Issue #431, merged PR #416): running a Robot suite with the
...               listener attached must persist ``agentic_metrics`` rows per
...               executed test case, keyed to the active harness session.
...
...               Each test brackets a real ``rfc harness start`` session in a
...               throwaway git repo + sqlite DB, generates a minimal inner
...               suite emitting synthetic ``RFC_DATA:llm_metrics`` payloads,
...               and runs it as a separate OS process with the listener
...               attached — the same wiring as the Makefile ``LISTENER`` var.
...               No LLM is invoked; assertions are pure Python.

Library           rfc.harness_listener_kw.HarnessListenerRunner    WITH NAME    Listener

Test Setup        Create Workspace
Test Teardown     Remove Workspace

Test Tags         harness-listener    tier:1    verify:python    axis:harness

*** Keywords ***
Create Workspace
    ${root}=    Evaluate    tempfile.mkdtemp(prefix="harness-listener-")    modules=tempfile
    ${ws}=    Listener.Create Listener Workspace    ${root}
    Set Test Variable    ${WS}    ${ws}

Remove Workspace
    Evaluate    shutil.rmtree($WS["path"], ignore_errors=True)    modules=shutil

Run Suite With Listener
    [Documentation]    Run the generated inner suite with the listener
    ...                attached and assert the Robot run itself passed.
    [Arguments]    &{kwargs}
    ${result}=    Listener.Run Inner Suite    ${WS}    &{kwargs}
    Should Be Equal As Integers    ${result}[rc]    0    Inner robot run failed: ${result}[stderr]
    RETURN    ${result}

*** Test Cases ***
Listener Persists Metric Rows Per Test Case
    [Documentation]    The core #431 contract: a run with N emitting tests
    ...                yields tokens_in / tokens_out / latency_ms rows for
    ...                each test, keyed to the harness session_id.
    ${session_id}=    Listener.Start Harness Session    ${WS}
    Listener.Write Inner Suite    ${WS}    metrics    metrics    metrics
    Run Suite With Listener
    ${rows}=    Listener.Get Metric Rows    ${WS}    ${session_id}
    Length Should Be    ${rows}    9
    FOR    ${key}    IN    tokens_in    tokens_out    latency_ms
        ${per_key}=    Listener.Get Metric Rows    ${WS}    ${session_id}    ${key}
        Length Should Be    ${per_key}    3
    END
    FOR    ${row}    IN    @{rows}
        Should Be Equal    ${row}[session_id]    ${session_id}
        Should Not Be Empty    ${row}[recorded_at]
        Should Be True    ${row}[metric_value] > 0
    END

Grader Score Is Captured Alongside Metrics
    [Documentation]    A test that also emits ``RFC_DATA:score`` produces a
    ...                grader_score row with the emitted value.
    ${session_id}=    Listener.Start Harness Session    ${WS}
    Listener.Write Inner Suite    ${WS}    metrics+score
    Run Suite With Listener
    ${scores}=    Listener.Get Metric Rows    ${WS}    ${session_id}    grader_score
    Length Should Be    ${scores}    1
    Should Be Equal As Numbers    ${scores}[0][metric_value]    0.75

Non Emitting Test Produces No Rows
    [Documentation]    Rows track emissions, not test count: a silent test
    ...                contributes nothing while its neighbour still does.
    ${session_id}=    Listener.Start Harness Session    ${WS}
    Listener.Write Inner Suite    ${WS}    silent    metrics
    Run Suite With Listener
    ${rows}=    Listener.Get Metric Rows    ${WS}    ${session_id}
    Length Should Be    ${rows}    3

Unreachable Database Never Fails The Run
    [Documentation]    CLAUDE.md skip-and-log: with DATABASE_URL pointing at
    ...                an impossible path, the inner run still passes and no
    ...                rows reach the real database.
    ${session_id}=    Listener.Start Harness Session    ${WS}
    Listener.Write Inner Suite    ${WS}    metrics
    Run Suite With Listener    database_url=sqlite:///${WS}[path]/no/such/dir/x.db
    ${rows}=    Listener.Get Metric Rows    ${WS}    ${session_id}
    Should Be Empty    ${rows}

No Harness Session Means No Rows
    [Documentation]    Without ``rfc harness start`` there is no sidecar; the
    ...                listener warns and persists nothing, and the run passes.
    Listener.Write Inner Suite    ${WS}    metrics
    Run Suite With Listener
    ${total}=    Listener.Count All Metric Rows    ${WS}
    Should Be Equal As Integers    ${total}    0
