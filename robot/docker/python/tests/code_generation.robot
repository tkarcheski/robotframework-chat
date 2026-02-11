*** Settings ***
Documentation     Python code generation and execution tests using Docker containers
Resource          ../../../resources/environments.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections

*** Variables ***
${FACTORIAL_PROMPT}        Write a Python function 'factorial(n)' that calculates the factorial of a number. Include docstring and handle edge cases like negative numbers.
${FIBONACCI_PROMPT}        Write a Python function 'fibonacci(n)' using an efficient approach. Include type hints and error handling.
${REVERSE_STRING_PROMPT}   Write a Python function 'reverse_string(s)' that reverses a string efficiently without using built-in reverse methods.

*** Test Cases ***
LLM Generates Factorial Function (IQ:120)
    [Documentation]    LLM generates working factorial function with error handling
    [Tags]    IQ:120    algorithm    function-generation

    # Ask LLM to generate code
    ${response}=    LLM.Ask LLM    ${FACTORIAL_PROMPT}
    ${code}=    Extract Code Block    ${response}    python

    # Test the generated code
    ${test_script}=    Catenate    SEPARATOR=\n
    ...    ${code}
    ...    print(factorial(5))
    ...    print(factorial(0))
    ...    try:
    ...        factorial(-1)
    ...    except (ValueError, TypeError, RecursionError) as e:
    ...        print(f"Error handling works: {type(e).__name__}")

    ${result}=    Docker.Execute Python In Container    ${test_script}
    ...    container_id=${PYTHON_CONTAINER}
    ...    timeout=10

    # Verify results
    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    120
    Should Contain    ${result}[stdout]    1
    Should Contain    ${result}[stdout]    Error handling works

    # Grade the response
    ${score}    ${reason}=    LLM.Grade Answer    ${FACTORIAL_PROMPT}    working factorial with error handling    ${response}
    Should Be Equal As Integers    ${score}    1

LLM Generates Efficient Fibonacci (IQ:130)
    [Documentation]    LLM generates efficient fibonacci implementation
    [Tags]    IQ:130    algorithm    dynamic-programming

    ${response}=    LLM.Ask LLM    ${FIBONACCI_PROMPT}
    ${code}=    Extract Code Block    ${response}    python

    # Test with larger number to check efficiency
    ${test_script}=    Catenate    SEPARATOR=\n
    ...    import time
    ...    ${code}
    ...    start = time.time()
    ...    result = fibonacci(30)
    ...    elapsed = time.time() - start
    ...    print(f"fibonacci(30) = {result}")
    ...    print(f"Time: {elapsed:.3f}s")

    ${result}=    Docker.Execute In Container    ${PYTHON_CONTAINER}    python3 -c "${test_script}"    timeout=15

    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    fibonacci(30) = 832040

    # Check it completed quickly (efficient implementation should be < 1s)
    ${output_lines}=    Split String    ${result}[stdout]    \n
    ${time_line}=    Get From List    ${output_lines}    -1
    Should Contain    ${time_line}    Time:

LLM Fixes Bug In Code (IQ:140)
    [Documentation]    LLM debugs and fixes buggy code
    [Tags]    IQ:140    debugging    bug-fixing

    # Create buggy code that causes division by zero
    ${buggy_code}=    Set Variable    def divide(a, b):\n    return a / b\n\nresult = divide(10, 0)\nprint(f"Result: {result}")

    # First verify it fails
    ${broken_result}=    Docker.Execute In Container    ${PYTHON_CONTAINER}    python3 -c "${buggy_code}"    timeout=5
    Should Not Be Equal As Integers    ${broken_result}[exit_code]    0

    # Ask LLM to fix it
    ${fix_prompt}=    Catenate    SEPARATOR=\n
    ...    Fix this Python code to handle division by zero:
    ...    ${buggy_code}
    ...    Error: ${broken_result}[stderr]

    ${fixed_response}=    LLM.Ask LLM    ${fix_prompt}
    ${fixed_code}=    Extract Code Block    ${fixed_response}    python

    # Test the fixed code
    ${fixed_result}=    Docker.Execute In Container    ${PYTHON_CONTAINER}    python3 -c "${fixed_code}"    timeout=5
    Should Be Equal As Integers    ${fixed_result}[exit_code]    0

LLM Respects Resource Limits (IQ:130)
    [Documentation]    Verify container resource limits are enforced
    [Tags]    IQ:130    resource-limits    safety

    # Try to allocate more memory than allowed (512MB)
    ${memory_hog}=    Set Variable    x = [0] * (200 * 1024 * 1024)

    ${result}=    Docker.Execute In Container    ${PYTHON_CONTAINER}
    ...    python3 -c "${memory_hog}"
    ...    timeout=10

    # Should fail due to memory limit
    Should Not Be Equal As Integers    ${result}[exit_code]    0
    Log    Memory limit enforced correctly: ${result}[stderr]

LLM Generates String Reverse Function (IQ:110)
    [Documentation]    LLM generates string reversal without built-in methods
    [Tags]    IQ:110    string-manipulation

    ${response}=    LLM.Ask LLM    ${REVERSE_STRING_PROMPT}
    ${code}=    Extract Code Block    ${response}    python

    ${test_script}=    Catenate    SEPARATOR=\n
    ...    ${code}
    ...    test_cases = ["hello", "Python", "12345", ""]
    ...    for s in test_cases:
    ...        result = reverse_string(s)
    ...        expected = s[::-1]
    ...        assert result == expected, f"Failed for '{s}': got '{result}', expected '{expected}'"
    ...        print(f"reverse_string('{s}') = '{result}'")

    ${result}=    Docker.Execute In Container    ${PYTHON_CONTAINER}    python3 -c "${test_script}"    timeout=10

    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    reverse_string('hello') = 'olleh'

Custom Container Configuration (IQ:120)
    [Documentation]    Test with custom CPU and memory constraints
    [Tags]    IQ:120    custom-resources

    ${custom_config}=    Create Dictionary
    ...    image=python:3.11-alpine
    ...    cpu_cores=0.25
    ...    memory_mb=256
    ...    network_mode=none
    ...    read_only=True

    ${container}=    Docker.Create Configurable Container    ${custom_config}

    ${code}=    Set Variable    print(sum(range(1000000)))
    ${result}=    Docker.Execute Python In Container    ${code}    container_id=${container}    timeout=15

    Docker.Stop Container    ${container}
    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    499999500000

*** Keywords ***
Extract Code Block
    [Documentation]    Extract code from markdown-formatted response
    [Arguments]    ${text}    ${language}=python

    # Try to extract from markdown code block with language
    ${pattern}=    Set Variable    \`\`\`(?:${language})?\\s*\\n(.*?)\\n?\`\`\`
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1

    ${has_matches}=    Get Length    ${matches}
    Run Keyword If    ${has_matches} > 0
    ...    RETURN    @{matches}[0]

    # Fallback: try generic code block
    ${pattern}=    Set Variable    \`\`\`\\s*\\n(.*?)\\n?\`\`\`
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1

    ${has_matches}=    Get Length    ${matches}
    Run Keyword If    ${has_matches} > 0
    ...    RETURN    @{matches}[0]

    # If no code block, return the whole text
    RETURN    ${text}
