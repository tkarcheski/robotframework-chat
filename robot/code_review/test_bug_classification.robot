*** Settings ***
Documentation     Bug classification tests — identify the bug type.
...
...               Each test presents code with one known bug and asks the
...               LLM to classify it from a fixed vocabulary.  Graded by
...               exact match against the expected category — no secondary
...               LLM grader.

Resource          code_review.resource
Default Tags      code_review    bug_classification    tier:1    verify:python
Test Timeout      3 minutes

*** Variables ***
${INFINITE_CODE}
...    def countdown(n):
...        while n > 0:
...            print(n)
...        return 0

${OBO_CODE}
...    def sum_elements(arr):
...        total = 0
...        for i in range(0, len(arr) + 1):
...            total += arr[i]
...        return total

${LEAK_CODE}
...    def load_data(path):
...        f = open(path, "rb")
...        content = f.read()
...        return content

*** Test Cases ***

Classify Infinite Loop Bug
    [Documentation]    The countdown loop never terminates — expected: infinite-loop.
    [Tags]    infinite_loop
    Classify Bug And Pass    ${INFINITE_CODE}    infinite-loop

Classify Off-By-One Bug
    [Documentation]    The loop iterates one past the last index — expected: off-by-one.
    [Tags]    off_by_one
    Classify Bug And Pass    ${OBO_CODE}    off-by-one

Classify Resource Leak Bug
    [Documentation]    The file handle is never closed — expected: resource-leak.
    [Tags]    resource_leak
    Classify Bug And Pass    ${LEAK_CODE}    resource-leak
