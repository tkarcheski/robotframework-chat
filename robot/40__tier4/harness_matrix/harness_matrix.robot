*** Settings ***
Documentation     Cross-harness conformance matrix (#173): the SAME fixture task
...               run under each AVAILABLE coding-agent harness through the public
...               ``rfc.harness_keywords`` surface, asserting identical contract
...               outcomes via ``rfc.agent_verifiers``. Every run brackets an
...               ``agentic_harnesses`` session, so it lands in the DB spine.
...
...               LIVE and probe-gated. Each harness leg is a real subprocess (real
...               git worktree, real agent) and skips cleanly when its CLI is
...               absent — ``codex`` is absent by default and joins the matrix with
...               no suite change once installed. The ``claude-code`` leg spends API
...               tokens, so it is gated behind ``HARNESS_MATRIX_CLAUDE=1`` on top of
...               the live gate. The ``opencode`` + local-Ollama leg is the cheap
...               leg. The whole suite is gated behind ``HARNESS_MATRIX_LIVE=1``; the
...               deterministic twin (no models, no tokens) is
...               ``tests/test_harness_keywords.py``.
...
...               Feeds public-repo issue rfc#596 (public keyword surface).

Library           rfc.harness_keywords.HarnessKeywords
Library           rfc.agentic_coding_keywords.AgenticCodingKeywords
Library           OperatingSystem
Resource          harness_matrix.resource

Suite Setup       Require Live Matrix

Test Tags         tier:4    verify:python    harness-matrix    category:live

*** Variables ***
${TASK}           Add a greet helper named greet to src/rfc/example.py and cover it with a test.
${BASE_BRANCH}    main
# Model override for the opencode leg. Empty uses the repo opencode.json default
# (local Ollama). Set to e.g. ollama/qwen3-coder:30b-a3b-q4_K_M to pin a model.
${OPENCODE_MODEL}    ${EMPTY}

*** Test Cases ***
Opencode Honors The Harness Contract
    [Documentation]    The cheap leg: opencode + local Ollama runs the fixture
    ...                through the keywords and its AgentRun passes the shared
    ...                verifier assertions.
    [Tags]    harness:opencode
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
    Skip If    "%{HARNESS_MATRIX_CLAUDE=}" != "1"
    ...    Set HARNESS_MATRIX_CLAUDE=1 to run the token-spending claude-code leg
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

*** Keywords ***
Require Live Matrix
    [Documentation]    Gate the whole suite: it drives real agents and git.
    Skip If    "%{HARNESS_MATRIX_LIVE=}" != "1"
    ...    Set HARNESS_MATRIX_LIVE=1 to run the live cross-harness matrix

Skip Unless Harness Available
    [Documentation]    Probe-gate a leg: skip cleanly when the CLI is absent.
    [Arguments]    ${tool}
    ${available}=    Harness Is Available    ${tool}
    Skip If    not $available    ${tool} CLI is not installed; skipping its leg

New Matrix Workspace
    [Documentation]    Throwaway git repo + sqlite DB for one harness leg.
    ${root}=    Evaluate    tempfile.mkdtemp(prefix="harness-matrix-")    modules=tempfile
    ${ws}=    Create Harness Workspace    ${root}
    RETURN    ${ws}

Harness Run Should Conform
    [Documentation]    The identical contract outcomes every harness must honor:
    ...                the run is attributed to its harness, lands on the harness's
    ...                branch namespace, is retrievable as the session transcript,
    ...                and never commits while tests are red.
    [Arguments]    ${run}    ${tool}    ${prefix}
    Should Be Equal    ${run.agent_id}    ${tool}
    Should Start With    ${run.branch_name}    ${prefix}/
    ${transcript}=    Get Agent Transcript
    Should Be Equal    ${transcript}    ${run}
    No Commit Should Occur While Tests Red    ${run}
