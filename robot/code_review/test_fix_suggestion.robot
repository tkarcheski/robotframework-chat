*** Settings ***
Documentation     Fix suggestion tests — propose the correct code change.
...
...               Each test presents buggy code and checks that the LLM's
...               suggested fix contains the specific tokens needed to resolve
...               the bug.  Graded by keyword recall — no secondary LLM grader.

Resource          code_review.resource
Default Tags      code_review    fix_suggestion    tier:1    verify:python
Test Timeout      3 minutes

*** Variables ***
${LEAK_CODE}
...    def read_config(path):
...        f = open(path, "r")
...        data = f.read()
...        return data

${OBO_CODE}
...    def last_element(arr):
...        return arr[len(arr)]

${INFINITE_CODE}
...    def sum_to_n(n):
...        total = 0
...        i = 0
...        while i <= n:
...            total += i
...        return total

*** Test Cases ***

Fix Resource Leak With Context Manager
    [Documentation]    The fix must use 'with' to ensure the file is closed.
    [Tags]    resource_leak    context_manager
    ${fix_kws}=    Create List    with    close
    Suggest Fix And Pass    ${LEAK_CODE}    ${fix_kws}    min_score=0.5

Fix Off-By-One Index Error
    [Documentation]    The fix must correct the index from len(arr) to len(arr)-1.
    [Tags]    off_by_one
    ${fix_kws}=    Create List    len
    Suggest Fix And Pass    ${OBO_CODE}    ${fix_kws}    min_score=1.0

Fix Infinite Loop By Adding Increment
    [Documentation]    The fix must add an increment to i (i += 1 or i = i + 1).
    [Tags]    infinite_loop
    ${fix_kws}=    Create List    i += 1
    Suggest Fix And Pass    ${INFINITE_CODE}    ${fix_kws}    min_score=1.0
