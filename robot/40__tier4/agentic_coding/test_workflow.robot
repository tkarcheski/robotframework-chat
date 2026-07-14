*** Settings ***
Documentation     Complex workflow scenarios (#292): rebase recovery,
...               regression detection, and bisectable history. Each test
...               replays a prerecorded AgentRun fixture and asserts against
...               it with deterministic Python-backed verifiers — can the
...               agent recover from a conflict, does it notice a regression
...               its change caused, and is every commit it produced green?

Resource          agentic_coding.resource

*** Test Cases ***
Claude Code Resolves Mid Flight Rebase Without Dropping Either Side
    [Documentation]    Upstream moves mid-session and conflicts with the agent's
    ...                change. The agent must rebase, merge both sides of the
    ...                conflict (no --ours/--theirs/--skip), and continue.
    [Tags]    tier:1    verify:python    scenario:rebase_mid_flight    category:workflow
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=rebase_mid_flight
    Rebase Should Be Resolved Without Dropping Changes    ${run}
    Run Should Not Contain Forbidden Commands    ${run}

Claude Code Reruns Tests After Completing The Rebase
    [Documentation]    After the rebase completes the agent must rerun the test
    ...                suite before proceeding — a rebase is a code change.
    [Tags]    tier:1    verify:python    scenario:rebase_mid_flight    category:workflow
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=rebase_mid_flight
    Commands Should Appear In Order    ${run}    git rebase origin/claude-code-staging    git rebase --continue    uv run pytest

Claude Code Never Commits While Tests Are Red
    [Documentation]    A refactor breaks an unseen downstream caller. The agent
    ...                must surface the red suite and fix it before committing —
    ...                no git commit may land while the latest pytest is red.
    [Tags]    tier:1    verify:python    scenario:regression_detection    category:workflow
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=regression_detection
    No Commit Should Occur While Tests Red    ${run}
    Run Should Not Contain Forbidden Commands    ${run}

Claude Code Detects The Regression Its Refactor Caused
    [Documentation]    The agent must run the full suite after the refactor and
    ...                only commit after the downstream fix turns it green.
    [Tags]    tier:1    verify:python    scenario:regression_detection    category:workflow
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=regression_detection
    Commands Should Appear In Order    ${run}    uv run pytest    git commit

Claude Code Multi Step Feature Commits Are Bisectable
    [Documentation]    Every commit of the multi-step feature must replay green:
    ...                each SHA is checked out and the test suite passes there.
    [Tags]    tier:1    verify:python    scenario:bisectable_commits    category:workflow
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=bisectable_commits
    Every Commit Should Be Green    ${run}    test_command=uv run pytest
    All Commits Should Match Convention    ${run}
