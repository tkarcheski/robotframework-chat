*** Settings ***
Documentation     Bug detection tests.
...
...               Presents the LLM with a Python code snippet containing a
...               single bug and a multiple-choice question (A–D).  The LLM
...               must write the correct letter on the first line of its response.
...               Graded deterministically by letter extraction — Tier 1 / verify:python.

Resource          code_review.resource

Default Tags      code_review    bug_detection    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Mutable Default Argument Bug
    [Documentation]    Detect the shared-mutable-default-argument anti-pattern.
    [Tags]    tier:1    verify:python    bug_detection    python
    Assert Bug Identified Correctly    ${BUG_SCENARIOS}[0]

Off By One Index Error
    [Documentation]    Detect the off-by-one IndexError when accessing the last element.
    [Tags]    tier:1    verify:python    bug_detection    python
    Assert Bug Identified Correctly    ${BUG_SCENARIOS}[1]

List Mutation During Iteration Bug
    [Documentation]    Detect that modifying a list while iterating over it skips elements.
    [Tags]    tier:1    verify:python    bug_detection    python
    Assert Bug Identified Correctly    ${BUG_SCENARIOS}[2]

Missing Parentheses On Method Call
    [Documentation]    Detect that `text.split` (missing parens) returns a method, not a list.
    [Tags]    tier:1    verify:python    bug_detection    python
    Assert Bug Identified Correctly    ${BUG_SCENARIOS}[3]

Division By Zero On Empty Input
    [Documentation]    Detect the ZeroDivisionError risk when computing the average of an empty list.
    [Tags]    tier:1    verify:python    bug_detection    python
    Assert Bug Identified Correctly    ${BUG_SCENARIOS}[4]
