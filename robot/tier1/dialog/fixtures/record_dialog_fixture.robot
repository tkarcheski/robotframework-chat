*** Settings ***
Documentation     Inner fixture for the dialog recorder e2e suite (#437).
...
...               Driven by robot/tier1/dialog/tests/dialog_recorder_e2e.robot via
...               ``Run Dialog Fixture Suite``, which runs this file in a
...               child robot process with rfc.dialog_listener.DialogListener
...               attached. The test opens a recording bracket, emits three
...               deterministic turns (no LLM), closes the bracket, and
...               writes the recording id to %{DIALOG_E2E_ID_FILE} so the
...               outer suite can assert the persisted rows.
...
...               Standalone runs (e.g. a full robot/ sweep) skip cleanly:
...               without DIALOG_E2E_ID_FILE there is no outer suite to
...               verify the rows, so recording would only pollute the DB.

Library           rfc.dialog_recorder.DialogRecorder
Library           rfc.dialog_e2e_keywords.DialogE2EKeywords
Library           OperatingSystem

Test Tags         dialog    dialog-e2e-fixture    tier:1    verify:python

*** Test Cases ***
Record A Minimal Dialog
    [Documentation]    Start a recording, emit 3 turns, end the recording.
    Skip If    "%{DIALOG_E2E_ID_FILE=}" == ""
    ...    Fixture only runs when driven by dialog_recorder_e2e.robot (DIALOG_E2E_ID_FILE unset)
    ${recording_id}=    Start Dialog Recording    source_type=live    agent_id=dialog-e2e-fixture
    Emit Dialog Turn    ${recording_id}    user         Hello recorder, this is turn one.
    Emit Dialog Turn    ${recording_id}    assistant    Acknowledged — turn two, persisted via DialogListener.
    Emit Dialog Turn    ${recording_id}    user         Closing the bracket now.
    ${ended_id}=    End Dialog Recording
    Should Be Equal    ${ended_id}    ${recording_id}
    Create File    %{DIALOG_E2E_ID_FILE}    ${recording_id}
