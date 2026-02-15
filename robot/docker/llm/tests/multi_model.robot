*** Settings ***
Documentation     LLM-in-Docker multi-model comparison tests
Resource          ../../../resources/llm_containers.resource
Resource          ../../../resources/container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String

Test Timeout      5 minutes

Test Tags         llm    multi-model    docker

*** Variables ***
${CODE_PROMPT}          Write a Python function to sort a list of integers efficiently
${ALGO_PROMPT}          Explain the time and space complexity of merge sort with code example
${DEBUG_PROMPT}         Find and fix the bug in this code: def add(a, b): return a + b + 1

*** Keywords ***
Extract Code From Response
    [Documentation]    Extract first markdown code block from LLM response (python or generic)
    [Arguments]    ${text}

    # Use DOTALL so '.' matches newlines
    ${pattern}=    Set Variable    (?s)```python\s*(.*?)\s*```
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1

    ${count}=    Get Length    ${matches}
    IF    ${count} > 0
        ${code}=    Set Variable    ${matches}[0]
        RETURN    ${code}
    END

    # Fallback to any fenced code block
    ${pattern}=    Set Variable    (?s)```\s*(.*?)\s*```
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1
    ${count}=    Get Length    ${matches}
    IF    ${count} > 0
        ${code}=    Set Variable    ${matches}[0]
        RETURN    ${code}
    END

    # Return full text if no code block found
    RETURN    ${text}

Check Ollama Health On Endpoint
    [Arguments]    ${endpoint}
    ${response}=    GET    ${endpoint}/api/tags    timeout=5    expected_status=any
    Should Be Equal As Integers    ${response.status_code}    200

*** Test Cases ***
Compare Models On Code Generation (IQ:130)
    [Documentation]    Same coding prompt, different models, compare quality
    [Tags]    IQ:130    comparison    code-generation
    [Setup]    Switch LLM Model    llama3

    # Generate code with current model
    ${response}=    LLM.Ask LLM    ${CODE_PROMPT}
    ${code}=    Extract Code From Response    ${response}

    # Execute the generated code
    ${test_script}=    Catenate    SEPARATOR=\n
    ...    ${code}
    ...    print(sort_list([3, 1, 4, 1, 5, 9, 2, 6]))
    ...    print(sort_list([]))
    ...    print(sort_list([5]))

    ${result}=    Docker.Execute Python In Container    ${test_script}    timeout=15

    # Verify it works
    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    [1, 1, 2, 3, 4, 5, 6, 9]

    # Grade the response
    ${score}    ${reason}=    LLM.Grade Answer    ${CODE_PROMPT}    working sort function    ${response}
    Should Be Equal As Integers    ${score}    1

LLM Algorithm Explanation (IQ:120)
    [Documentation]    Test algorithm explanation capabilities
    [Tags]    IQ:120    algorithm    explanation

    ${response}=    LLM.Ask LLM    ${ALGO_PROMPT}

    # Should contain complexity analysis
    Should Contain    ${response}    O(n log n)
    Should Contain    ${response}    space

    # Try to extract and run code
    ${code}=    Extract Code From Response    ${response}
    Run Keyword And Ignore Error    Docker.Execute Python In Container    ${code}    timeout=10

LLM Container Resource Usage (IQ:110)
    [Documentation]    Monitor resource usage during LLM inference
    [Tags]    IQ:110    monitoring    resources

    # Start a request
    ${response}=    LLM.Ask LLM    Write a short Python script to calculate prime numbers

    # Check container metrics
    ${metrics}=    Get Container Metrics During Test

    # Log resource usage
    Log    LLM inference used ${metrics}[cpu_percent]% CPU and ${metrics}[memory_usage_mb] MB memory

    # Memory should be reasonable (< 4GB)
    Should Be True    ${metrics}[memory_usage_mb] < 4096

Custom LLM Configuration (IQ:140)
    [Documentation]    Test with custom resource allocation for LLM
    [Tags]    IQ:140    custom-config

    # Find available port for custom container
    ${custom_port}=    Docker.Find Available Port    11434    11500
    ${custom_port_mapping}=    Create Dictionary    11434/tcp=${custom_port}

    # Create custom Ollama container with more resources
    ${custom_config}=    Create Dictionary
    ...    image=ollama/ollama:latest
    ...    cpu_cores=1.0
    ...    memory_mb=2048
    ...    scratch_mb=512
    ...    network_mode=bridge
    ...    ports=${custom_port_mapping}
    ...    read_only=False

    ${container}=    Docker.Create Configurable Container    ${custom_config}    rfc-ollama-custom

    # Wait for API to be ready
    ${custom_endpoint}=    Set Variable    http://localhost:${custom_port}
    Wait Until Keyword Succeeds    60s    2s    Check Ollama Health On Endpoint    ${custom_endpoint}

    # Pull model
    Docker.Execute In Container    ${container}    ollama pull llama3    timeout=300

    # Test inference
    LLM.Set LLM Endpoint    ${custom_endpoint}
    LLM.Set LLM Model    llama3

    ${response}=    LLM.Ask LLM    What is 2 + 2?
    Should Contain    ${response}    4

    # Cleanup
    Docker.Stop Container    ${container}
