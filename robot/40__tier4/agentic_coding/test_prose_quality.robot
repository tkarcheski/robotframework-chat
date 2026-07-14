*** Settings ***
Documentation     Tier:3 prose quality of agent output, judged by an LLM panel:
...
...               * Clarifying questions must be grounded in concrete repo
...                 files/symbols, not generic boilerplate.
...               * PR bodies must actually explain how to review.
...               * Commit subjects must truthfully describe their files.
...
...               Requires AGENT_PROSE_GRADER_MODELS (3+ comma-separated
...               models); tests skip with a clear reason when unset.

Resource          agentic_coding.resource

*** Test Cases ***
Claude Code Clarifying Questions Are Grounded In The Repo
    [Documentation]    Judge panel: each MC question on the ambiguous task references a concrete file or symbol.
    [Tags]    tier:3    verify:llms    scenario:ambiguous_task    category:prose
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=ambiguous_task
    Clarifying Questions Should Be Grounded    ${run}

Claude Code PR Body Explains How To Review
    [Documentation]    Judge panel: the TDD scenario's PR body names a starting file and sequences key changes.
    [Tags]    tier:3    verify:llms    scenario:tdd_red_green    category:prose
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=tdd_red_green
    PR Body Should Explain How To Review    ${run}

Claude Code Commit Subjects Match Their Changes
    [Documentation]    Judge panel: each commit subject truthfully describes only its files_changed.
    [Tags]    tier:3    verify:llms    scenario:tdd_red_green    category:prose
    ${run}=    Run Coding Agent Scenario    agent=${AGENT_ID}    scenario=tdd_red_green
    Commits Should Match Their Changes    ${run}
