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
    [Tags]    tier:4    verify:python    agent:claude_code    sandbox:tier4_bug_fix    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_bug_fix    variant=good
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Bug Fix Agent Leaving Scratch Files Is Flagged For Churn
    [Documentation]    The churn variant fixes the bug but leaves notes.txt
    ...                and debug.log behind; the harness must flag the
    ...                unexpected file churn even though tests pass.
    [Tags]    tier:4    verify:python    agent:claude_code    sandbox:tier4_bug_fix    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_bug_fix    variant=churn
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Report Unexpected File Churn    ${result}

Careful Refactor Keeps Hidden Regression Guard Green
    [Documentation]    The careful refactor preserves the behaviour the
    ...                hidden (unmentioned) test depends on: full suite green.
    [Tags]    tier:4    verify:python    agent:claude_code    sandbox:tier4_regression_guard    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_regression_guard    variant=careful
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Tests Should Pass    ${result}
    Sandbox Should Have No Unexpected File Churn    ${result}

Naive Refactor Surfaces Hidden Regression
    [Documentation]    The naive refactor breaks the hidden contract test;
    ...                the harness must surface the regression as a failing
    ...                post-run suite instead of reporting success.
    [Tags]    tier:4    verify:python    agent:claude_code    sandbox:tier4_regression_guard    category:sandbox
    ${result}=    Run Sandboxed Coding Scenario    agent=${AGENT_ID}    scenario=tier4_regression_guard    variant=naive
    Sandbox Agent Command Should Succeed    ${result}
    Sandbox Should Surface Test Failure    ${result}
