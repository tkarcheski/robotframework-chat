*** Settings ***
Documentation     Terminal workflow and shell command tests
Resource          ../../../resources/environments.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections

*** Variables ***
${PROJECT_SETUP_PROMPT}    Generate shell commands to: create a directory called 'myproject', enter it, create a file 'main.py' with 'print("Hello")', create a file 'README.md', and list all files

*** Test Cases ***
LLM Generates Project Setup Commands (IQ:120)
    [Documentation]    LLM generates correct shell workflow
    [Tags]    IQ:120    workflow    project-setup

    ${response}=    LLM.Ask LLM    ${PROJECT_SETUP_PROMPT}

    # Extract and execute commands
    ${commands}=    Extract Shell Commands    ${response}

    # Execute each command in sequence
    FOR    ${cmd}    IN    @{commands}
        Continue For Loop If    '${cmd}' == ''
        Log    Executing: ${cmd}
        ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    ${cmd}
        Log    Output: ${result}[stdout]
    END

    # Verify directory structure
    ${list_result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    ls -la myproject/
    Should Contain    ${list_result}[stdout]    main.py
    Should Contain    ${list_result}[stdout]    README.md

LLM Generates File Processing Pipeline (IQ:130)
    [Documentation]    LLM creates file processing command pipeline
    [Tags]    IQ:130    pipeline    file-processing

    # Create test data
    Docker.Execute In Container    ${SHELL_CONTAINER}    echo -e "apple\nbanana\napple\ncherry\nbanana\napple" > /tmp/fruits.txt

    ${prompt}=    Set Variable    Write a shell command to count occurrences of each line in /tmp/fruits.txt, sorted by count descending

    ${response}=    LLM.Ask LLM    ${prompt}
    ${command}=    Extract Shell Commands    ${response}

    # Execute the command
    ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    @{command}[0]

    # Verify output shows correct counts
    Should Contain    ${result}[stdout]    3
    Should Contain    ${result}[stdout]    apple

Container Is Network Isolated (IQ:110)
    [Documentation]    Verify container network isolation
    [Tags]    IQ:110    security    network

    # Try to access network
    ${result}=    Docker.Execute In Container    ${SHELL_CONTAINER}    wget -q --timeout=5 http://google.com

    # Should fail (network is disabled)
    Should Not Be Equal As Integers    ${result}[exit_code]    0

Custom Shell Container (IQ:120)
    [Documentation]    Create shell container with custom resources
    [Tags]    IQ:120    custom-resources

    ${config}=    Create Dictionary
    ...    image=alpine:latest
    ...    cpu_cores=0.25
    ...    memory_mb=64
    ...    network_mode=none
    ...    read_only=True

    ${container}=    Docker.Create Configurable Container    ${config}

    # Should still work with limited resources
    ${result}=    Docker.Execute In Container    ${container}    echo "Resource constrained"
    Should Be Equal As Integers    ${result}[exit_code]    0
    Should Contain    ${result}[stdout]    Resource constrained

    Docker.Stop Container    ${container}

Container Preserves State Between Commands (IQ:130)
    [Documentation]    Verify container state is maintained
    [Tags]    IQ:130    state-management

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

*** Keywords ***
Extract Shell Commands
    [Documentation]    Extract shell commands from LLM response
    [Arguments]    ${text}

    ${commands}=    Create List

    # Look for code blocks first
    ${pattern}=    Set Variable    \`\`\`(?:bash|sh|shell)?\\n(.*?)\\n\`\`\`
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1

    ${has_matches}=    Get Length    ${matches}
    Run Keyword If    ${has_matches} > 0
    ...    Split To Lines    @{matches}[0]    ${commands}

    # If no code block, split lines and filter
    ${lines}=    Get Lines Containing String    ${text}    $
    ${filtered}=    Create List
    FOR    ${line}    IN    @{lines}
        ${stripped}=    Strip String    ${line}
        # Skip comments and empty lines
        Run Keyword If    '${stripped}' != '' and not '${stripped}'.startswith('#')
        ...    Append To List    ${filtered}    ${stripped}
    END

    ${has_filtered}=    Get Length    ${filtered}
    Run Keyword If    ${has_filtered} > 0
    ...    RETURN    ${filtered}

    RETURN    ${commands}

Split To Lines
    [Arguments]    ${text}    ${result_list}
    ${lines}=    Split String    ${text}    \n
    FOR    ${line}    IN    @{lines}
        ${stripped}=    Strip String    ${line}
        Run Keyword If    '${stripped}' != ''
        ...    Append To List    ${result_list}    ${stripped}
    END
