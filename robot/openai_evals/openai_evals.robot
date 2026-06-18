*** Settings ***
Documentation    OpenAI Evals harness scaffold — Issue #621.
...              Real eval cases live in a future issue once the external
...              dataset dependency is available in CI.

*** Variables ***
${PLACEHOLDER}    stub

*** Test Cases ***
Scaffold Placeholder
    [Documentation]    Stub test to keep the suite runnable until real eval
    ...                cases are wired up.
    [Tags]    tier:1    verify:functional
    Log    OpenAI Evals suite loaded — no live cases yet
