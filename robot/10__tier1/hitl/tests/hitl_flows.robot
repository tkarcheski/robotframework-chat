*** Settings ***
Documentation     Human-in-the-Loop MVP flows (#384).
...
...               Exercises the ``hitl_interactions`` contract settled with
...               @rpelevin on the issue: goal, clarification, approval, and
...               input records share one table, but only an ``approval`` row
...               — bound to the exact action id and args digest — ever
...               authorizes execution. Clarifications resume reasoning yet
...               never grant authority (the explicit negative case below),
...               and stale/expired approvals fail closed.
...
...               Non-interactive by design: the "human" side of every flow
...               is a table update (``Resolve Interaction``) against a
...               throwaway per-suite SQLite database — no LLM, no Docker,
...               no live UI. Slack / web-UI transports are post-v2 and will
...               resolve these same rows.

Library           Collections
Library           rfc.hitl_keywords.HitlKeywords    AS    Hitl

Suite Setup       Create Hitl Suite Database
Suite Teardown    Remove Hitl Suite Database

Test Tags         hitl    tier:1    verify:python    axis:none

*** Variables ***
${ACTION_ID}          deploy:production:rollout
${WAIT_TIMEOUT}       5
${SHORT_EXPIRY}       0.4
${EXPIRY_MARGIN}      0.7s

*** Test Cases ***
Goal Is Recorded As A Distinct Resolved Event
    [Documentation]    A human-authored goal lands as its own ``goal`` row,
    ...    already resolved, and is retrievable as the session's current goal.
    ${sid}=    New Session Id
    ${goal_id}=    Hitl.Set Goal    ${sid}    Ship the HITL MVP
    ${current}=    Hitl.Get Current Goal    ${sid}
    Should Be Equal    ${current}    Ship the HITL MVP
    ${row}=    Hitl.Get Interaction    ${goal_id}
    Should Be Equal    ${row}[kind]      goal
    Should Be Equal    ${row}[status]    approved
    Should Not Be Empty    ${row}[resolved_at]

Clarification Resolves Via Table Update And Resumes
    [Documentation]    The non-interactive default: the human answers by
    ...    updating the interaction row; the waiting agent picks up the
    ...    response and resumes.
    ${sid}=    New Session Id
    ${cid}=    Hitl.Request Clarification    ${sid}    Which region should the rollout target?
    ${status}=    Hitl.Check Approval Status    ${cid}
    Should Be Equal    ${status}    pending
    Hitl.Resolve Interaction    ${cid}    approved    response=us-east-1 only
    ${row}=    Hitl.Wait For Human Input    ${cid}    timeout=${WAIT_TIMEOUT}
    Should Be Equal    ${row}[status]      approved
    Should Be Equal    ${row}[response]    us-east-1 only

Approval Bound To Action And Digest Authorizes Execution
    [Documentation]    rpelevin test 2: a high-risk approval is bound to the
    ...    exact pending action id and args digest — and only an approved,
    ...    unexpired row opens the gate.
    ${sid}=    New Session Id
    &{args}=    Create Dictionary    target=prod    replicas=3
    ${aid}=    Hitl.Request Human Approval    ${sid}    Roll out to production?    ${ACTION_ID}    ${args}
    ${allowed}=    Hitl.Is Action Approved    ${sid}    ${ACTION_ID}    ${args}
    Should Not Be True    ${allowed}    msg=a pending approval must not authorize
    Hitl.Resolve Interaction    ${aid}    approved    response=go ahead
    ${allowed}=    Hitl.Is Action Approved    ${sid}    ${ACTION_ID}    ${args}
    Should Be True    ${allowed}
    ${authorizer}=    Hitl.Ensure Action Approved    ${sid}    ${ACTION_ID}    ${args}
    Should Be Equal    ${authorizer}    ${aid}

Clarification Response Must Not Authorize The Action
    [Documentation]    THE negative case (rpelevin tests 1 and 6): a resolved
    ...    clarification — even one spoofing the same action id and args —
    ...    resumes the session but never authorizes the high-risk tool. A
    ...    separate approval event with the matching id and digest is
    ...    required before the action may run.
    ${sid}=    New Session Id
    &{args}=    Create Dictionary    target=prod    replicas=3
    ${cid}=    Hitl.Request Clarification    ${sid}    Should I run the production rollout?
    ...    target_action_id=${ACTION_ID}    args=${args}
    ${resumed}=    Hitl.Resolve Interaction    ${cid}    approved    response=yes, go ahead
    Should Be Equal    ${resumed}[status]    approved    msg=clarification must still resume the session
    ${allowed}=    Hitl.Is Action Approved    ${sid}    ${ACTION_ID}    ${args}
    Should Not Be True    ${allowed}    msg=a clarification response must never authorize execution
    Run Keyword And Expect Error    HitlApprovalError: *never authorizes*
    ...    Hitl.Ensure Action Approved    ${sid}    ${ACTION_ID}    ${args}
    # Only the separate approval event unblocks the action.
    ${aid}=    Hitl.Request Human Approval    ${sid}    Roll out to production?    ${ACTION_ID}    ${args}
    Hitl.Resolve Interaction    ${aid}    approved
    ${allowed}=    Hitl.Is Action Approved    ${sid}    ${ACTION_ID}    ${args}
    Should Be True    ${allowed}

Args Digest Mismatch Fails Closed
    [Documentation]    An approval authorizes the exact arguments the human
    ...    saw — changing them afterwards voids it.
    ${sid}=    New Session Id
    &{approved_args}=    Create Dictionary    target=prod    replicas=3
    &{changed_args}=     Create Dictionary    target=prod    replicas=30
    ${aid}=    Hitl.Request Human Approval    ${sid}    Roll out to production?    ${ACTION_ID}    ${approved_args}
    Hitl.Resolve Interaction    ${aid}    approved
    ${allowed}=    Hitl.Is Action Approved    ${sid}    ${ACTION_ID}    ${changed_args}
    Should Not Be True    ${allowed}    msg=changed args must void the approval
    Run Keyword And Expect Error    HitlApprovalError: *digest*
    ...    Hitl.Ensure Action Approved    ${sid}    ${ACTION_ID}    ${changed_args}

Expired Approval Fails Closed
    [Documentation]    rpelevin test 3: a stale approval — granted, then
    ...    past its expiry — no longer authorizes anything.
    ${sid}=    New Session Id
    &{args}=    Create Dictionary    target=prod    replicas=3
    ${aid}=    Hitl.Request Human Approval    ${sid}    Roll out to production?    ${ACTION_ID}    ${args}
    ...    expires_in=${SHORT_EXPIRY}
    Hitl.Resolve Interaction    ${aid}    approved    response=go ahead
    Sleep    ${EXPIRY_MARGIN}    reason=let the approval expire
    ${allowed}=    Hitl.Is Action Approved    ${sid}    ${ACTION_ID}    ${args}
    Should Not Be True    ${allowed}    msg=an expired approval must fail closed
    Run Keyword And Expect Error    HitlApprovalError: *expire*
    ...    Hitl.Ensure Action Approved    ${sid}    ${ACTION_ID}    ${args}

Unanswered Input Expires Fail Closed On Timeout
    [Documentation]    ``Wait For Human Input`` gives up after its timeout,
    ...    persists the ``expired`` status to the table, and a late human
    ...    response is rejected rather than applied.
    ${sid}=    New Session Id
    ${iid}=    Hitl.Request Human Input    ${sid}    Provide the deploy window
    ${row}=    Hitl.Wait For Human Input    ${iid}    timeout=0.5    poll_interval=0.1
    Should Be Equal    ${row}[status]    expired
    ${persisted}=    Hitl.Get Interaction    ${iid}
    Should Be Equal    ${persisted}[status]    expired
    Run Keyword And Expect Error    HitlApprovalError: *
    ...    Hitl.Resolve Interaction    ${iid}    approved    response=too late

*** Keywords ***
Create Hitl Suite Database
    [Documentation]    Throwaway per-suite SQLite database — deterministic,
    ...    no external services (skip-and-log is unnecessary here).
    ${root}=    Evaluate    tempfile.mkdtemp(prefix="rfc-hitl-")    modules=tempfile
    Set Suite Variable    ${HITL_ROOT}    ${root}
    Hitl.Connect Hitl Database    db_path=${root}${/}hitl.db

Remove Hitl Suite Database
    Evaluate    shutil.rmtree($HITL_ROOT, ignore_errors=True)    modules=shutil

New Session Id
    [Documentation]    Fresh session id per test so rows never bleed between
    ...    test cases sharing the suite database.
    ${sid}=    Evaluate    uuid.uuid4().hex    modules=uuid
    RETURN    ${sid}
