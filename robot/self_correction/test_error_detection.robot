*** Settings ***
Documentation     Error detection tests — math, code, and off-by-one errors.
...
...               Presents the LLM with content containing a deliberate, known
...               error and checks whether the model identifies it.  Uses
...               deterministic substring matching (tier:1): the correct value
...               or fix must appear in the model's response.

Resource          self_correction.resource

Default Tags      self_correction    error_detection    tier:1    verify:python

Test Timeout      2 minutes

*** Test Cases ***

Arithmetic Error — 17 Times 8
    [Documentation]    The claim that 17 × 8 = 146 is wrong; the correct answer is 136.
    ...                The response must contain "136".
    Assert Error Detected
    ...    There is exactly one arithmetic error in the following calculation: 17 × 8 = 146. Identify the error and state the correct result.
    ...    136

Arithmetic Error — Percentage Calculation
    [Documentation]    The claim that 15% of 200 is 35 is wrong; the correct answer is 30.
    Assert Error Detected
    ...    There is exactly one error in the following percentage calculation: 15% of 200 = 35. Find and correct the error.
    ...    30

Code Bug — Addition Disguised As Subtraction
    [Documentation]    The function uses subtraction but the name says "add". The fix uses "+".
    Assert Error Detected
    ...    Find the bug in this Python function and state the corrected line:\n\ndef add(a, b):\n    return a - b
    ...    a + b

Code Bug — Square Using Addition
    [Documentation]    The square function uses addition instead of multiplication.
    Assert Error Detected
    ...    Find the bug in this Python function and state the corrected line:\n\ndef square(n):\n    return n + n
    ...    n * n

Off-By-One — Range Iteration Count
    [Documentation]    range(1, 10) iterates 9 times (1 through 9), not 10 times.
    Assert Error Detected
    ...    Find the error in the following statement: "The Python loop 'for i in range(1, 10)' will execute exactly 10 times." Correct the statement.
    ...    9

Off-By-One — Zero-Indexed Array
    [Documentation]    A 5-element array has valid indices 0 through 4, not 0 through 5.
    Assert Error Detected
    ...    Find the error: "A Python list with 5 elements has valid indices from 0 to 5." Correct the statement.
    ...    4

Unit Error — Distance Calculation
    [Documentation]    60 km/h × 2 h = 120 km, not 120 m. The unit is wrong.
    Assert Error Detected
    ...    Find the error in this physics calculation: "A car travels at 60 km/h for 2 hours, so it covers 60 × 2 = 120 m." State the corrected result with the correct unit.
    ...    km

Factorial Base Case Error
    [Documentation]    The factorial of 0 is 1, not 0. A model claiming 0! = 0 is wrong.
    Assert Error Detected
    ...    Find the error in this statement: "By definition, 0! (zero factorial) equals 0." State the correct value.
    ...    1
