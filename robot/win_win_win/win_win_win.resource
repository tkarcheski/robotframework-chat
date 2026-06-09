*** Settings ***
Documentation     Shared keywords and variables for win-win-win-interview skill tests.

Library           rfc.skill_keywords.SkillKeywords
Variables         ${CURDIR}/variables/prompts.yaml

*** Variables ***
# Path to the win-win-win-interview AgentSkill directory containing SKILL.md.
# Overridable via the SKILL_PATH environment variable so CI can point at
# wherever the skill has been checked out.
${SKILL_PATH}    %{SKILL_PATH=${CURDIR}/../../skills/unverified/win-win-win-interview}

*** Keywords ***
Run Win Win Win Test Case
    [Documentation]    Run a single win-win-win-interview test case and assert it passed.
    [Arguments]    ${test_case}
    ${result}=    Run Skill Test Case    ${SKILL_PATH}    ${test_case}
    Assert Skill Grade Passed    ${result}
