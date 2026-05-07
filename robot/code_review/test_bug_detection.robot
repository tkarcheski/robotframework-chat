*** Settings ***
Documentation     Bug detection tests — find the bug in a code snippet.
...
...               Each test presents code with one planted bug and checks
...               that the LLM's response contains keywords specific to
...               that bug.  Graded by keyword recall — no secondary LLM grader.

Resource          code_review.resource
Default Tags      code_review    bug_detection    tier:1    verify:python
Test Timeout      3 minutes

*** Variables ***
# -------------------------------------------------------------------
# Off-by-one: loop upper bound is len(arr)+1 instead of len(arr)
# -------------------------------------------------------------------
${OBO_CODE}
...    def find_max(arr):
...        max_val = arr[0]
...        for i in range(1, len(arr) + 1):
...            if arr[i] > max_val:
...                max_val = arr[i]
...        return max_val

# -------------------------------------------------------------------
# Missing None check: dict.get() may return None
# -------------------------------------------------------------------
${NULL_CODE}
...    def get_user_age(users, user_id):
...        user = users.get(user_id)
...        return user["age"]

# -------------------------------------------------------------------
# Infinite loop: loop variable never modified
# -------------------------------------------------------------------
${INFINITE_CODE}
...    def countdown(n):
...        while n > 0:
...            print(n)
...        return 0

# -------------------------------------------------------------------
# Resource leak: file opened but never closed
# -------------------------------------------------------------------
${LEAK_CODE}
...    def read_config(path):
...        f = open(path, "r")
...        data = f.read()
...        return data

*** Test Cases ***

Off-By-One In Loop Upper Bound
    [Documentation]    The loop uses range(1, len(arr)+1) which reads past
    ...                the last valid index, causing an IndexError.
    [Tags]    off_by_one    index_error
    ${keywords}=    Create List    off-by-one    IndexError
    Find Bug And Pass    ${OBO_CODE}    off-by-one in range upper bound
    ...    ${keywords}    min_score=0.5

Missing None Check After Dict Lookup
    [Documentation]    users.get(user_id) may return None; subscripting None raises TypeError.
    [Tags]    null_check    type_error
    ${keywords}=    Create List    None    user
    Find Bug And Pass    ${NULL_CODE}    missing None check on dict.get result
    ...    ${keywords}    min_score=0.5

Infinite Loop Due To Missing Decrement
    [Documentation]    The while loop never modifies n so it runs forever.
    [Tags]    infinite_loop
    ${keywords}=    Create List    infinite    n
    Find Bug And Pass    ${INFINITE_CODE}    infinite loop — n never decremented
    ...    ${keywords}    min_score=0.5

Resource Leak From Unclosed File
    [Documentation]    The file handle is never closed, leaking a resource.
    [Tags]    resource_leak
    ${keywords}=    Create List    close    with
    Find Bug And Pass    ${LEAK_CODE}    file opened but never closed
    ...    ${keywords}    min_score=0.5
