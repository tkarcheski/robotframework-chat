*** Settings ***
Documentation     End-to-end tier:4 scenarios: a disposable repo is seeded
...               into a Docker container, an agent runs live inside it under
...               the resource caps from config/local_agents.yaml, and the
...               harness verifies (a) the scenario's tests pass afterwards
...               and (b) no unexpected file churn occurred.
...
...               Agent variants are scripted shell agents shipped with each
...               scenario fixture — deterministic stand-ins until the live
...               Claude Code adapter (#288) plugs into the same harness.

Resource          ../agentic_coding.resource

*** Test Cases ***
Bug Fix Agent Turns Failing Test Green
    [Documentation]    A failing test is committed up front; after the agent
    ...                run the whole unittest suite must pass inside the
    ...                container with changes confined to allowed paths.
    [Tags]    tier:4    verify:python    sandbox:tier4_bug_fix    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_bug_fix    variant=good
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Bug Fix Agent Leaving Scratch Files Is Flagged For Churn
    [Documentation]    The churn variant fixes the bug but leaves notes.txt
    ...                and debug.log behind; the harness must flag the
    ...                unexpected file churn even though tests pass.
    [Tags]    tier:4    verify:python    sandbox:tier4_bug_fix    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_bug_fix    variant=churn
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Report Unexpected File Churn    ${result}

Careful Refactor Keeps Hidden Regression Guard Green
    [Documentation]    The careful refactor preserves the behaviour the
    ...                hidden (unmentioned) test depends on: full suite green.
    [Tags]    tier:4    verify:python    sandbox:tier4_regression_guard    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_regression_guard    variant=careful
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Naive Refactor Surfaces Hidden Regression
    [Documentation]    The naive refactor breaks the hidden contract test;
    ...                the harness must surface the regression as a failing
    ...                post-run suite instead of reporting success.
    [Tags]    tier:4    verify:python    sandbox:tier4_regression_guard    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_regression_guard    variant=naive
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Should Surface Test Failure    ${result}

API-Preserving Patch Keeps The Public Signature Stable
    [Documentation]    The preserve variant fixes the missing-key bug without
    ...                changing get_setting's public signature; the whole suite
    ...                (visible behaviour + hidden API contract) goes green with
    ...                changes confined to the allowed path.
    [Tags]    tier:4    verify:python    sandbox:tier4_api_stability    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_api_stability    variant=preserve
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Signature-Widening Patch Surfaces Public API Regression
    [Documentation]    The widen variant fixes the behaviour but adds a parameter
    ...                to get_setting; the visible tests still pass, so the hidden
    ...                public-API contract must surface the changed signature as a
    ...                failing post-run suite.
    [Tags]    tier:4    verify:python    sandbox:tier4_api_stability    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_api_stability    variant=widen
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Should Surface Test Failure    ${result}

Shared-Interface Fix Repairs Every Consumer
    [Documentation]    The shared_fix variant repairs the money.format_amount
    ...                interface, so both the visible invoice consumer and the
    ...                hidden receipt consumer go green with no unexpected churn.
    [Tags]    tier:4    verify:python    sandbox:tier4_interface_refactor    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_interface_refactor    variant=shared_fix
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Local Patch Bypassing The Interface Surfaces Hidden Consumer Regression
    [Documentation]    The local_patch variant fixes only the invoice consumer and
    ...                leaves the shared interface unfixed; the visible test passes
    ...                but the hidden second consumer stays broken, so the harness
    ...                must surface the regression.
    [Tags]    tier:4    verify:python    sandbox:tier4_interface_refactor    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_interface_refactor    variant=local_patch
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Should Surface Test Failure    ${result}

Linear Refactor Stays Within The Performance Budget
    [Documentation]    The efficient variant fixes the behaviour with a single set
    ...                lookup; both the visible tests and the hidden linear
    ...                comparison-count budget pass with no unexpected churn.
    [Tags]    tier:4    verify:python    sandbox:tier4_perf_guard    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_perf_guard    variant=efficient
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Quadratic Refactor Surfaces Performance Regression
    [Documentation]    The quadratic variant returns correct answers (visible
    ...                tests pass) but keeps the list scan; the hidden performance
    ...                contract must surface the blown comparison budget as a
    ...                failing post-run suite.
    [Tags]    tier:4    verify:python    sandbox:tier4_perf_guard    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_perf_guard    variant=quadratic
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Should Surface Test Failure    ${result}

Codegen Cleaning Its Scratch File Stays Within The Churn Budget
    [Documentation]    The clean variant generates the module and removes its
    ...                scratch .build.tmp intermediate; tests pass and the net
    ...                churn is exactly the allowed generated output.
    [Tags]    tier:4    verify:python    sandbox:tier4_codegen_churn    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_codegen_churn    variant=clean
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Codegen Leaving Its Scratch File Is Flagged For Churn
    [Documentation]    The leftover variant generates the module but leaves the
    ...                scratch .build.tmp behind; the harness must flag the
    ...                unexpected file churn even though tests pass.
    [Tags]    tier:4    verify:python    sandbox:tier4_codegen_churn    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_codegen_churn    variant=leftover
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Report Unexpected File Churn    ${result}

Live Harness Solves Bug Fix Scenario
    [Documentation]    Opt-in live evidence (owner egress decision 2): a real
    ...                coding-agent harness runs HOST-SIDE against the seeded
    ...                bug_fix repo while the network-isolated container still
    ...                verifies the tests pass and no unexpected churn. Skipped
    ...                unless ${SANDBOX_HARNESS} names a harness, so the scripted
    ...                stand-ins stay the deterministic CI default; an absent
    ...                harness CLI or Docker daemon also skips cleanly.
    [Tags]    tier:4    verify:python    sandbox:tier4_bug_fix    category:sandbox    cost:live
    Skip If    '${SANDBOX_HARNESS}' == '${EMPTY}'    Set -v SANDBOX_HARNESS:<tool> (e.g. opencode) to drive a live harness
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_bug_fix    variant=${SANDBOX_HARNESS}    harness=${SANDBOX_HARNESS}    harness_model=${SANDBOX_HARNESS_MODEL}
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}
