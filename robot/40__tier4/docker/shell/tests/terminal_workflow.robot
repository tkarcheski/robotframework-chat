*** Settings ***
Documentation     Terminal workflow and shell command tests
Resource          ../../../../resources/environments.resource
Resource          ../../../../resources/code_extraction.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String

*** Variables ***
${PROJECT_SETUP_PROMPT}    Generate shell commands to: create a directory called 'myproject', enter it, create a file 'main.py' with 'print("Hello")', create a file 'README.md', and list all files

*** Test Cases ***
LLM Generates Project Setup Commands (IQ:120)
    [Documentation]    Can the LLM generate shell commands to set up a project directory with files?
    [Tags]    IQ:120    workflow    project-setup    tier:4    verify:robot

    ${response}=    LLM.Ask LLM    ${PROJECT_SETUP_PROMPT}

    # Extract and execute commands
    ${commands}=    Extract Shell Commands    ${response}

    # Execute commands in a single shell session to preserve directory changes
    # Join commands with ; to execute sequentially in same session
    ${command_string}=    Evaluate    "; ".join(${commands})
    ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    ${command_string}
    Log    Output: ${result}[stdout]

    # Verify directory structure
    ${list_result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    ls -la myproject/
    Should Contain    ${list_result}[stdout]    main.py
    Should Contain    ${list_result}[stdout]    README.md

LLM Generates File Processing Pipeline (IQ:130)
    [Documentation]    Can the LLM write a shell pipeline to count line occurrences sorted by frequency?
    [Tags]    IQ:130    pipeline    file-processing    tier:4    verify:robot

    # Create test data
    Docker.Execute In Container    ${SHELL_CONTAINER}    echo -e "apple\nbanana\napple\ncherry\nbanana\napple" > /tmp/fruits.txt

    ${prompt}=    Set Variable    Write a shell command to count occurrences of each line in /tmp/fruits.txt, sorted by count descending

    ${response}=    LLM.Ask LLM    ${prompt}
    ${command}=    Extract Shell Commands    ${response}

    # Execute the command
    ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    ${command}[0]

    # Verify output shows correct counts
    Should Contain    ${result}[stdout]    3
    Should Contain    ${result}[stdout]    apple

Container Is Network Isolated (IQ:110)
    [Documentation]    Can the container block outbound network access (wget to google.com)?
    [Tags]    IQ:110    security    network    tier:1    verify:robot

    # Try to access network
    ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    wget -q --timeout=5 http://google.com

    # Should fail (network is disabled)
    Should Not Be Equal As Integers    ${result}[exit_code]    0

Custom Shell Container (IQ:120)
    [Documentation]    Can a custom Alpine container (0.25 CPU, 64MB, read-only) execute shell commands?
    [Tags]    IQ:120    custom-resources    tier:1    verify:robot

    ${config}=    Create Dictionary
    ...    image=alpine:latest
    ...    cpu_cores=0.25
    ...    memory_mb=64
    ...    network_mode=none
    ...    read_only=True
    ...    command=sleep 30
    ...    auto_remove=False

    ${container}=    Docker.Create Configurable Container    ${config}

    # Should still work with limited resources
    ${result}=    Docker.Execute In Container    ${container}    echo "Resource constrained"
    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    Resource constrained

    Docker.Stop Container    ${container}

Container Preserves State Between Commands (IQ:130)
    [Documentation]    Can the container preserve file state between sequential commands?
    [Tags]    IQ:130    state-management    tier:1    verify:robot

    # Create a file
    Docker.Execute In Container    ${SHELL_CONTAINER}    echo "test data" > /tmp/persist.txt

    # Read it back
    ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    cat /tmp/persist.txt
    Should Contain    ${result}[stdout]    test data

    # Modify it
    Docker.Execute In Container    ${SHELL_CONTAINER}    echo "more data" >> /tmp/persist.txt

    # Verify append worked
    ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    cat /tmp/persist.txt
    Should Contain    ${result}[stdout]    test data
    Should Contain    ${result}[stdout]    more data
