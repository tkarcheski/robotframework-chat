*** Settings ***
Documentation     Behavioral tests for the win-win-win-interview AgentSkill.
...
...               Each test case prepends the skill's SKILL.md to a user prompt
...               and grades the response against an LLM-as-judge for expected
...               and prohibited behaviors. The skill should produce responses
...               that:
...                 - gather context before deciding,
...                 - frame decisions in terms of user, team, and business "wins",
...                 - resist premature solutions and lectures.

Resource          win_win_win.resource

Suite Setup       Skip Unless Skill Available    ${SKILL_PATH}

Default Tags      win_win_win    tier:2    verify:llm

Test Timeout      250 minutes

*** Test Cases ***

TP-01 Greeting Opens Interview
    [Documentation]    Skill should open with an interview rather than jumping to a redesign.
    Run Win Win Win Test Case    ${TP_01_GREETING_OPENS_INTERVIEW}

TP-02 Surfaces Stakeholders
    [Documentation]    Skill should surface multiple affected stakeholders.
    Run Win Win Win Test Case    ${TP_02_SURFACES_STAKEHOLDERS}

TP-03 Win Win Win Framing
    [Documentation]    Skill should explicitly frame decisions as user/team/business wins.
    Run Win Win Win Test Case    ${TP_03_WIN_WIN_WIN_FRAMING}

TP-04 Resists Premature Solutions
    [Documentation]    Skill should ask for requirements before naming a "best" solution.
    Run Win Win Win Test Case    ${TP_04_RESISTS_PREMATURE_SOLUTIONS}

TP-05 Summarizes Before Deciding
    [Documentation]    Skill should summarize trade-offs before recommending.
    Run Win Win Win Test Case    ${TP_05_SUMMARIZES_BEFORE_DECIDING}

TP-06 Invites Pushback
    [Documentation]    Skill should invite pushback rather than rubber-stamping a plan.
    Run Win Win Win Test Case    ${TP_06_INVITES_PUSHBACK}

TP-07 Names Tradeoffs
    [Documentation]    Skill should name concrete trade-offs on both sides of a decision.
    Run Win Win Win Test Case    ${TP_07_NAMES_TRADEOFFS}

TP-08 Flags Missing Context
    [Documentation]    Skill should request audience and goals before drafting.
    Run Win Win Win Test Case    ${TP_08_FLAGS_MISSING_CONTEXT}

TP-09 Does Not Lecture
    [Documentation]    Skill should honor MVP scope and not over-engineer.
    Run Win Win Win Test Case    ${TP_09_DOES_NOT_LECTURE}

TP-10 Honors User Goal
    [Documentation]    Skill should adapt to idea-validation scope.
    Run Win Win Win Test Case    ${TP_10_HONORS_USER_GOAL}
