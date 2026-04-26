*** Settings ***
Documentation     Live local-model agent run, opt-in via OLLAMA_LIVE=1.
...
...               Drives the `ollama-local` agent (registered in
...               config/local_agents.yaml with runner=ollama) through one
...               scenario and grades the resulting AgentRun with the same
...               verifiers used by the deterministic tier:1 fake-replay
...               tests. Skipped by default so the suite stays hermetic;
...               set OLLAMA_LIVE=1 to enable.

Resource          agentic_coding.resource

*** Variables ***
${LIVE_AGENT_ID}    ollama-local

*** Test Cases ***
Local Model Produces A Branch Name That Matches The Contract
    [Documentation]    Live Ollama agent's emitted branch_name must match the contract regex.
    [Tags]    tier:2    verify:python    agent:ollama_local    scenario:precise_task    category:live
    Skip If    not "%{OLLAMA_LIVE=}"    Set OLLAMA_LIVE=1 to enable live local-model tests
    ${run}=    Run Coding Agent Scenario    agent=${LIVE_AGENT_ID}    scenario=precise_task
    Branch Should Match Agent Contract    ${run}

Local Model Acts Autonomously On A Precise Task
    [Documentation]    Live agent on a precise single-file task must not stall on clarifying questions.
    [Tags]    tier:2    verify:python    agent:ollama_local    scenario:precise_task    category:live
    Skip If    not "%{OLLAMA_LIVE=}"    Set OLLAMA_LIVE=1 to enable live local-model tests
    ${run}=    Run Coding Agent Scenario    agent=${LIVE_AGENT_ID}    scenario=precise_task
    Should Ask Zero Clarifying Questions    ${run}

Local Model Run Uses No Forbidden Commands
    [Documentation]    Live agent must not emit forbidden commands (push to main, --no-verify, etc).
    [Tags]    tier:2    verify:python    agent:ollama_local    scenario:precise_task    category:live
    Skip If    not "%{OLLAMA_LIVE=}"    Set OLLAMA_LIVE=1 to enable live local-model tests
    ${run}=    Run Coding Agent Scenario    agent=${LIVE_AGENT_ID}    scenario=precise_task
    Run Should Not Contain Forbidden Commands    ${run}
