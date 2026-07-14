*** Settings ***
Documentation     Two-sided clarifying-question discipline:
...
...               * Ambiguous tasks MUST produce 2-4 grounded multiple-choice
...                 questions, with no source edits before the user replies.
...               * Precise single-file tasks MUST NOT stall on unnecessary
...                 clarifying questions.
...
...               Thresholds come from config/agent_contract.yaml, so changes
...               to CLAUDE.md propagate automatically without editing tests.

Resource          agentic_coding.resource

*** Test Cases ***
Claude Code Asks Grounded Multiple Choice Questions On Ambiguous Task
    [Documentation]    An ambiguous "clean up the metrics stuff" task must produce contract-bounded MC questions.
    [Tags]    tier:1    verify:python    scenario:ambiguous_task    category:clarify
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=ambiguous_task
    Should Ask Between N And M Questions    ${run}    2    4
    Questions Should Be Multiple Choice    ${run}

Claude Code Does Not Modify Source Before Clarifying Reply
    [Documentation]    Agent must not edit src/ while still waiting on the user's multiple-choice answer.
    [Tags]    tier:1    verify:python    scenario:ambiguous_task    category:clarify
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=ambiguous_task
    No Source Changes Should Exist Before    ${run}    command=git fetch    under=src/

Claude Code Acts Autonomously On Precise Single File Task
    [Documentation]    Precise, single-file task must not trigger clarification (per CLAUDE.md § Questions).
    [Tags]    tier:1    verify:python    scenario:precise_task    category:clarify
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=precise_task
    Should Ask Zero Clarifying Questions    ${run}
