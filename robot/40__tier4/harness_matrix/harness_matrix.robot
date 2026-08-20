*** Settings ***
Documentation     Cross-harness conformance matrix (#173): the SAME fixture task
...               run under each AVAILABLE coding-agent harness through the public
...               ``rfc.harness_keywords`` surface, asserting identical contract
...               outcomes via ``rfc.agent_verifiers``. Every run brackets an
...               ``agentic_harnesses`` session, so it lands in the DB spine.
...
...               Two run modes select how the conformance legs execute:
...
...               LIVE (``HARNESS_MATRIX_LIVE=1``) — each harness leg is a real
...               subprocess (real git worktree, real agent) and skips cleanly when
...               its CLI is absent. ``codex`` is absent by default and joins the
...               matrix with no suite change once installed. The ``claude-code`` leg
...               spends API tokens, so it is gated behind ``HARNESS_MATRIX_CLAUDE=1``
...               on top of the live gate. The ``opencode`` + local-Ollama leg is the
...               cheap leg.
...
...               REPLAY (``HARNESS_MATRIX_REPLAY=1``, or the S2 ``RFC_RUN_MODE=replay``
...               intent) — RFC-010 S3 (#261): the conformance legs read a recorded
...               transcript from ``recordings/`` instead of spawning an agent, so the
...               matrix runs in CI at ~0 tokens on every push with no harness
...               installed. A replayed leg stamps its provenance on the
...               ``agentic_harnesses`` spine (``replay_of_recording_id``), so a green
...               conformance cell is never mistaken for a fresh live pass — the same
...               discipline as ``cache_hit=True``. The comparison-battery legs are
...               live-only and skip under replay. This is the first-class-suite form
...               of the deterministic twin ``tests/test_harness_keywords.py``.
...
...               Feeds public-repo issue rfc#596 (public keyword surface).

Library           rfc.harness_keywords.HarnessKeywords
Library           rfc.agentic_coding_keywords.AgenticCodingKeywords
Library           rfc.harness_comparison.HarnessComparisonKeywords
Library           rfc.harness_significance.HarnessSignificanceKeywords
Library           OperatingSystem
Resource          harness_matrix.resource

Suite Setup       Require Matrix Mode

Test Tags         tier:4    verify:python    harness-matrix    category:live    axis:harness

*** Variables ***
${TASK}           Add a greet helper named greet to src/rfc/example.py and cover it with a test.
${BASE_BRANCH}    main
# Model override for the opencode leg. Empty uses the repo opencode.json default
# (local Ollama). Set to e.g. ollama/qwen3-coder:30b-a3b-q4_K_M to pin a model.
${OPENCODE_MODEL}    ${EMPTY}
# Council #675 variation 1: paired repeats for the within-harness reliability
# sample (variance-aware). Bounded so the live smoke stays cheap.
${MATRIX_REPEATS}    3

*** Test Cases ***
Opencode Honors The Harness Contract
    [Documentation]    The cheap leg: opencode + local Ollama runs the fixture
    ...                through the keywords and its AgentRun passes the shared
    ...                verifier assertions.
    [Tags]    harness:opencode    gold:harness    platinum:harness
    Skip Unless Harness Available    opencode
    ${ws}=    New Matrix Workspace
    Start Harness Session    tool=opencode    workspace=${ws}[path]
    ...    model=${OPENCODE_MODEL}    database_url=${ws}[database_url]
    ${run}=    Run Agent Task    task=${TASK}    base_branch=${BASE_BRANCH}
    Harness Run Should Conform    ${run}    opencode    opencode
    [Teardown]    End Session And Cleanup    ${ws}

Claude Code Honors The Harness Contract
    [Documentation]    The token-spending leg: gated behind HARNESS_MATRIX_CLAUDE=1
    ...                so the matrix never bills tokens unless the operator opts in.
    [Tags]    harness:claude-code    cost:tokens
    # The token gate applies to the LIVE leg only; a replayed leg spends no
    # tokens, so replay runs claude-code as a free CI conformance cell.
    ${replay}=    Replay Mode Requested
    IF    not ${replay}
        Skip If    "%{HARNESS_MATRIX_CLAUDE=}" != "1"
        ...    Set HARNESS_MATRIX_CLAUDE=1 to run the token-spending claude-code leg
    END
    Skip Unless Harness Available    claude-code
    ${ws}=    New Matrix Workspace
    Start Harness Session    tool=claude-code    workspace=${ws}[path]
    ...    database_url=${ws}[database_url]
    ${run}=    Run Agent Task    task=${TASK}    base_branch=${BASE_BRANCH}
    Harness Run Should Conform    ${run}    claude-code    claude
    [Teardown]    End Session And Cleanup    ${ws}

Codex Joins The Matrix When Installed
    [Documentation]    codex is absent on this box, so this leg skips cleanly and
    ...                joins with no suite change once the CLI is installed (#172
    ...                owner decision 3).
    [Tags]    harness:codex
    Skip Unless Harness Available    codex
    ${ws}=    New Matrix Workspace
    Start Harness Session    tool=codex    workspace=${ws}[path]
    ...    database_url=${ws}[database_url]
    ${run}=    Run Agent Task    task=${TASK}    base_branch=${BASE_BRANCH}
    Harness Run Should Conform    ${run}    codex    codex
    [Teardown]    End Session And Cleanup    ${ws}

Comparison Mode Records The Battery Per Harness
    [Documentation]    RFC-007 S2 (#218): instead of asserting equality, run
    ...                the discriminating tier:4 sandbox battery under opencode
    ...                (Tier A -- pinned to the same local Ollama model via the
    ...                #191 comparability gate) and RECORD per-run metrics to the
    ...                spine tagged with scenario_id + a shared battery_run_id,
    ...                rather than asserting cross-harness equality. Bounded live
    ...                smoke: the smallest scenario, N=1. The honest cross-harness
    ...                head-to-head needs a SECOND fixed-local harness (see the
    ...                rfc.harness_comparison docstring); this proves the recorder
    ...                writes pairable opencode rows. The McNemar gate is S4/#220.
    [Tags]    comparison    harness:opencode    gold:harness
    Skip In Replay Mode
    Skip Unless Harness Available    opencode
    ${ws}=    New Matrix Workspace
    ${scenarios}=    Create List    tier4_bug_fix
    ${report}=    Run Harness Comparison Battery    database_url=${ws}[database_url]
    ...    repeats=1    scenarios=${scenarios}
    Comparison Report Should Have Rows For    ${report}    opencode
    # RFC-007 S4 (#220): the McNemar gate over the recorded rows. With only the
    # one Tier-A leg available today, there is no second harness to pair, so the
    # gate must report an HONEST insufficient-pairs non-result (never a fake p).
    # It unlocks a real verdict the moment a second fixed-local harness records.
    ${verdict}=    Mcnemar Verdict For Harness Pair    ${report}    opencode    codex
    Mcnemar Verdict Should Be Insufficient    ${verdict}
    Log    McNemar gate: reason=${verdict.reason} (needs a second Tier-A harness to pair)
    [Teardown]    Remove Matrix Workspace If Created

Repeats Yield A Complete Within-Harness Reliability Sample
    [Documentation]    Council #675 variation (checklist item 1): run the same
    ...                fixture scenario under ONE harness for N paired repeats and
    ...                assert the spine records every repeat. The within-harness
    ...                reliability sample -- the substrate any variance / stability
    ...                estimate is computed over -- is honest only when complete: a
    ...                repeat that crashes or loses provenance leaves a hole, so a
    ...                leg that records fewer than N rows fails here. Varies exactly
    ...                the repeat index (model + harness held constant). Extends the
    ...                comparison smoke above (N=1) to a variance-bearing N; the
    ...                deterministic twin is ``tests/test_harness_comparison.py``.
    [Tags]    comparison    harness:opencode    gold:harness
    Skip In Replay Mode
    Skip Unless Harness Available    opencode
    ${ws}=    New Matrix Workspace
    ${scenarios}=    Create List    tier4_bug_fix
    ${report}=    Run Harness Comparison Battery    database_url=${ws}[database_url]
    ...    repeats=${MATRIX_REPEATS}    scenarios=${scenarios}
    Comparison Report Should Have Rows For    ${report}    opencode
    Length Should Be    ${report.rows}    ${MATRIX_REPEATS}
    ...    the within-harness reliability sample must record all ${MATRIX_REPEATS} repeats -- a dropped repeat is lost variance signal, not a pass
    [Teardown]    Remove Matrix Workspace If Created

Absent Optional Harness Skips Its Leg Without Failing
    [Documentation]    Council #675 variation (checklist item 6): an optional
    ...                harness that is not installed must be skip-and-logged, never
    ...                a hard failure (CLAUDE.md's skip-over-fail rule for optional
    ...                dependencies). This exercises the ABSENT path directly: it
    ...                runs only when ``claude-code`` is NOT installed, adds its leg
    ...                to the battery, and asserts the battery still records the
    ...                available ``opencode`` leg while reporting ``claude-code`` as
    ...                a skipped leg -- no exception, no failure row. A runner that
    ...                aborted the whole battery on the absent leg would fail here.
    ...                Restricting to the absent path also keeps this leg token-free.
    [Tags]    comparison    harness:claude-code    gold:harness
    Skip In Replay Mode
    Skip Unless Harness Available    opencode
    ${claude_available}=    Harness Is Available    claude-code
    Skip If    ${claude_available}
    ...    claude-code is installed; this case exercises the ABSENT-harness skip path (and avoids billing tokens)
    ${ws}=    New Matrix Workspace
    ${scenarios}=    Create List    tier4_bug_fix
    ${report}=    Run Harness Comparison Battery    database_url=${ws}[database_url]
    ...    repeats=1    scenarios=${scenarios}    include_claude=${True}
    Comparison Report Should Have Rows For    ${report}    opencode
    ${skipped_harnesses}=    Evaluate    [harness for harness, _reason in $report.skipped]
    Should Contain    ${skipped_harnesses}    claude-code
    ...    an absent optional harness must appear as a skipped leg, not a hard failure
    [Teardown]    Remove Matrix Workspace If Created

*** Keywords ***
Require Matrix Mode
    [Documentation]    Gate the whole suite on a selected run mode: LIVE
    ...                (``HARNESS_MATRIX_LIVE=1`` — real agents and git) or REPLAY
    ...                (``HARNESS_MATRIX_REPLAY=1`` / ``RFC_RUN_MODE=replay`` —
    ...                recorded transcripts, ~0 tokens). Skip when neither is set.
    ${live}=    Get Environment Variable    HARNESS_MATRIX_LIVE    ${EMPTY}
    ${replay}=    Replay Mode Requested
    IF    '${live}' != '1' and not ${replay}
        Skip    Set HARNESS_MATRIX_LIVE=1 (live) or HARNESS_MATRIX_REPLAY=1 (recorded replay) to run the cross-harness matrix
    END

Skip Unless Harness Available
    [Documentation]    Mode-aware leg gate: in live mode probe the CLI and skip
    ...                when it is absent; in replay mode require a recorded
    ...                transcript for the harness and skip when the corpus lacks
    ...                one. Either way an unavailable leg is skip-and-logged, never
    ...                a hard failure (CLAUDE.md skip-over-fail).
    [Arguments]    ${tool}
    ${replay}=    Replay Mode Requested
    IF    ${replay}
        ${available}=    Recording Available    ${tool}
        Skip If    not $available    no recorded transcript for ${tool}; skipping its replay leg
    ELSE
        ${available}=    Harness Is Available    ${tool}
        Skip If    not $available    ${tool} CLI is not installed; skipping its leg
    END

Skip In Replay Mode
    [Documentation]    The comparison-battery legs (RFC-007 S2/S4) drive the live
    ...                comparison recorder, not the recorded-transcript replay path
    ...                (RFC-010 S3 scopes the conformance legs). Skip them cleanly
    ...                under replay; live-mode behaviour is unchanged.
    ${replay}=    Replay Mode Requested
    Skip If    ${replay}    comparison battery is live-only; not part of the S3 replay slice

Remove Matrix Workspace If Created
    [Documentation]    Teardown for the comparison legs: remove the throwaway
    ...                workspace, tolerating a leg that skipped before
    ...                `New Matrix Workspace` ran (replay mode, or an absent
    ...                harness in live mode) so ``${ws}`` was never assigned.
    ${ws}=    Get Variable Value    ${ws}    ${NONE}
    IF    $ws is not None
        Remove Directory    ${ws}[path]    recursive=True
    END

New Matrix Workspace
    [Documentation]    Throwaway git repo + sqlite DB for one harness leg.
    ${root}=    Evaluate    tempfile.mkdtemp(prefix="harness-matrix-")    modules=tempfile
    ${ws}=    Create Harness Workspace    ${root}
    RETURN    ${ws}

Harness Run Should Conform
    [Documentation]    The identical contract outcomes every harness must honor:
    ...                the run is attributed to its harness, lands on the harness's
    ...                branch namespace, is retrievable as the session transcript,
    ...                did actual work (not a vacuous exit-0 no-op, #399), and
    ...                never commits while tests are red. The fixture ``${TASK}``
    ...                is work-producing, so the positive-work assertion is in
    ...                scope for every leg that uses this keyword.
    [Arguments]    ${run}    ${tool}    ${prefix}
    Should Be Equal    ${run.agent_id}    ${tool}
    Should Start With    ${run.branch_name}    ${prefix}/
    ${transcript}=    Get Agent Transcript
    Should Be Equal    ${transcript}    ${run}
    Run Should Do Positive Work    ${run}
    No Commit Should Occur While Tests Red    ${run}
    Run Provenance Should Match Mode

Run Provenance Should Match Mode
    [Documentation]    Honesty (RFC-010 §3, #261): a replayed leg MUST stamp its
    ...                provenance on the ``agentic_harnesses`` spine, so a green
    ...                conformance cell is never mistaken for a fresh live pass —
    ...                the same discipline as ``cache_hit=True``. A live leg must
    ...                carry no replay stamp.
    ${provenance}=    Get Session Provenance
    ${replay}=    Replay Mode Requested
    IF    ${replay}
        Should Not Be Empty    ${provenance}
        ...    a replayed leg must stamp replay_of_recording_id on the spine (green != live)
    ELSE
        Should Be Empty    ${provenance}
        ...    a live leg must not carry replay provenance
    END
