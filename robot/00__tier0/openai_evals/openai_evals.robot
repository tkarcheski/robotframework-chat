*** Settings ***
Documentation     OpenAI-Evals umbrella suite (#561/#562).
...
...               Scaffolding stub only (#621). The shared dataset loader
...               (rfc.eval_datasets), pluggable graders
...               (rfc.graders: exact/regex/llm_judge), and results-provenance
...               columns land in this issue; the actual benchmark suites
...               (#563/#564/#565/#566/#567) fan out under this group as they
...               are built. Until then this suite holds a single no-op smoke
...               test so `make robot-openai-evals` and `make robot-dryrun`
...               resolve cleanly with no external dataset or network.
Library           rfc.graders
Library           Collections
Test Tags         axis:model

*** Test Cases ***
OpenAI Evals Scaffolding Is Importable
    [Documentation]    Smoke test: the shared grader dispatcher resolves the
    ...                three built-in graders. No dataset download, no LLM call.
    [Tags]    tier:0    verify:robot    openai-evals
    ${exact}=    Get Grader    exact
    Should Not Be Equal    ${exact}    ${None}
    ${regex}=    Get Grader    regex
    Should Not Be Equal    ${regex}    ${None}
