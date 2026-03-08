*** Settings ***
Documentation     Reusable test environment setups for code execution
Resource          container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           OperatingSystem
Library           String
Library           DateTime

*** Variables ***
${SHARED_VOLUME_BASE}    /tmp/rfc-environments
${DEFAULT_TIMEOUT}       30

*** Keywords ***
Setup Python Environment
    [Documentation]    Setup Python container with shared workspace for the test suite
    [Arguments]    ${profile}=PYTHON_STANDARD    ${suite_name}=python-suite

    # Generate unique container name using timestamp
    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    ${suite_name}-${timestamp}

    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${unique_name}
    Create Directory    ${volume_path}

    ${volumes}=    Create Dictionary    ${volume_path}=/workspace:rw
    ${container_id}=    Create Container From Profile    ${profile}
    ...    container_name=rfc-${unique_name}
    ...    custom_volumes=${volumes}

    Set Global Variable    ${PYTHON_CONTAINER}    ${container_id}
    Set Global Variable    ${PYTHON_WORKSPACE}    ${volume_path}
    Set Global Variable    ${PYTHON_CONTAINER_NAME}    rfc-${unique_name}

    Log    Python environment ready: ${container_id} (${PYTHON_CONTAINER_NAME})
    RETURN    ${container_id}

Setup Node Environment
    [Documentation]    Setup Node.js container for JavaScript/TypeScript testing
    [Arguments]    ${profile}=NODE_STANDARD    ${suite_name}=node-suite

    # Generate unique container name using timestamp
    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    ${suite_name}-${timestamp}

    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${unique_name}
    Create Directory    ${volume_path}

    ${volumes}=    Create Dictionary    ${volume_path}=/workspace:rw
    ${container_id}=    Create Container From Profile    ${profile}
    ...    container_name=rfc-${unique_name}
    ...    custom_volumes=${volumes}

    Set Global Variable    ${NODE_CONTAINER}    ${container_id}
    Set Global Variable    ${NODE_WORKSPACE}    ${volume_path}
    Set Global Variable    ${NODE_CONTAINER_NAME}    rfc-${unique_name}

    Log    Node environment ready: ${container_id} (${NODE_CONTAINER_NAME})
    RETURN    ${container_id}

Setup Shell Environment
    [Documentation]    Setup shell container for terminal/command testing
    [Arguments]    ${profile}=ALPINE_SHELL    ${suite_name}=shell-suite

    # Generate unique container name using timestamp
    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    ${suite_name}-${timestamp}
    Set Global Variable    ${SHELL_CONTAINER_NAME}    rfc-${unique_name}

    # Create container with a command that keeps it running
    # Use read_only=False and user=root since shell tests need to create files
    ${profile_dict}=    Get Variable Value    ${${profile}}
    ${full_config}=    Create Dictionary    &{profile_dict}    command=sleep infinity    read_only=False    user=root
    ${container_id}=    Docker.Create Configurable Container    ${full_config}    ${SHELL_CONTAINER_NAME}

    # Install common tools
    Docker.Execute In Container    ${container_id}    apk add --no-cache bash coreutils

    Set Global Variable    ${SHELL_CONTAINER}    ${container_id}

    Log    Shell environment ready: ${container_id} (${SHELL_CONTAINER_NAME})
    RETURN    ${container_id}

Setup C Environment
    [Documentation]    Setup GCC container for C code compilation and execution
    [Arguments]    ${profile}=GCC_STANDARD    ${suite_name}=c-suite

    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    ${suite_name}-${timestamp}

    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${unique_name}
    Create Directory    ${volume_path}

    ${volumes}=    Create Dictionary    ${volume_path}=/workspace:rw
    ${profile_dict}=    Get Variable Value    ${${profile}}
    ${full_config}=    Create Dictionary    &{profile_dict}    command=sleep infinity    volumes=${volumes}
    ${container_id}=    Docker.Create Configurable Container    ${full_config}    rfc-${unique_name}

    Set Global Variable    ${C_CONTAINER}    ${container_id}
    Set Global Variable    ${C_WORKSPACE}    ${volume_path}
    Set Global Variable    ${C_CONTAINER_NAME}    rfc-${unique_name}

    Log    C environment ready: ${container_id} (${C_CONTAINER_NAME})
    RETURN    ${container_id}

Setup Rust Environment
    [Documentation]    Setup Rust container for Rust code compilation and execution
    [Arguments]    ${profile}=RUST_STANDARD    ${suite_name}=rust-suite

    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    ${suite_name}-${timestamp}

    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${unique_name}
    Create Directory    ${volume_path}

    ${volumes}=    Create Dictionary    ${volume_path}=/workspace:rw
    ${profile_dict}=    Get Variable Value    ${${profile}}
    ${full_config}=    Create Dictionary    &{profile_dict}    command=sleep infinity    volumes=${volumes}
    ${container_id}=    Docker.Create Configurable Container    ${full_config}    rfc-${unique_name}

    Set Global Variable    ${RUST_CONTAINER}    ${container_id}
    Set Global Variable    ${RUST_WORKSPACE}    ${volume_path}
    Set Global Variable    ${RUST_CONTAINER_NAME}    rfc-${unique_name}

    Log    Rust environment ready: ${container_id} (${RUST_CONTAINER_NAME})
    RETURN    ${container_id}

Setup Bash Environment
    [Documentation]    Setup Bash container for bash script execution
    [Arguments]    ${profile}=BASH_STANDARD    ${suite_name}=bash-suite

    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    ${suite_name}-${timestamp}

    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${unique_name}
    Create Directory    ${volume_path}

    ${volumes}=    Create Dictionary    ${volume_path}=/workspace:rw
    ${profile_dict}=    Get Variable Value    ${${profile}}
    ${full_config}=    Create Dictionary    &{profile_dict}    command=sleep infinity    volumes=${volumes}
    ${container_id}=    Docker.Create Configurable Container    ${full_config}    rfc-${unique_name}

    Set Global Variable    ${BASH_CONTAINER}    ${container_id}
    Set Global Variable    ${BASH_WORKSPACE}    ${volume_path}
    Set Global Variable    ${BASH_CONTAINER_NAME}    rfc-${unique_name}

    Log    Bash environment ready: ${container_id} (${BASH_CONTAINER_NAME})
    RETURN    ${container_id}

Write Source File In Container
    [Documentation]    Write source code to a file inside a container using a heredoc approach
    [Arguments]    ${container_var}    ${source_code}    ${dest_path}
    ${container_id}=    Get Variable Value    ${${container_var}}
    ${write_cmd}=    Catenate    SEPARATOR=
    ...    cat > ${dest_path} << 'RFCEOF'\n${source_code}\nRFCEOF
    ${result}=    Docker.Execute In Container    ${container_id}    ${write_cmd}    timeout=5
    Should Be Equal As Integers    ${result}[exit_code]    0    Failed to write source file: ${result}[stderr]
    RETURN    ${result}

Compile And Run In Container
    [Documentation]    Write source code, compile it, and run the binary in a container
    [Arguments]    ${container_var}    ${source_code}    ${source_file}    ${compile_cmd}    ${run_cmd}    ${timeout}=${DEFAULT_TIMEOUT}
    Write Source File In Container    ${container_var}    ${source_code}    /workspace/${source_file}
    ${container_id}=    Get Variable Value    ${${container_var}}
    # Compile
    ${compile_result}=    Docker.Execute In Container    ${container_id}    cd /workspace && ${compile_cmd}    timeout=${timeout}
    IF    ${compile_result}[exit_code] != 0
        RETURN    ${compile_result}
    END
    # Run
    ${run_result}=    Docker.Execute In Container    ${container_id}    cd /workspace && ${run_cmd}    timeout=${timeout}
    RETURN    ${run_result}

Teardown Environment
    [Documentation]    Cleanup container and remove shared volumes
    [Arguments]    ${container_var}    ${cleanup_volumes}=True

    ${container_id}=    Get Variable Value    ${${container_var}}
    Run Keyword If    '${container_id}' != '${None}'    Docker.Stop Container    ${container_id}

    Run Keyword If    ${cleanup_volumes}
    ...    Run Keyword And Ignore Error    Cleanup Workspace    ${container_var}

    Log    Environment cleaned up

Cleanup Workspace
    [Arguments]    ${container_var}
    ${workspace_var}=    Set Variable    ${container_var.replace('CONTAINER', 'WORKSPACE')}
    ${workspace}=    Get Variable Value    ${${workspace_var}}    ${None}
    Run Keyword If    '${workspace}' != '${None}' and '${workspace}' != ''
    ...    Remove Directory    ${workspace}    recursive=True

Execute Code In Environment
    [Documentation]    Execute code in the configured environment
    [Arguments]    ${container_var}    ${command}    ${timeout}=${DEFAULT_TIMEOUT}
    ${container_id}=    Get Variable Value    ${${container_var}}
    ${result}=    Docker.Execute In Container    ${container_id}    ${command}    timeout=${timeout}
    RETURN    ${result}

Copy File To Environment
    [Documentation]    Copy a file to the environment workspace
    [Arguments]    ${container_var}    ${host_file}    ${container_dest}=.
    ${container_id}=    Get Variable Value    ${${container_var}}
    ${workspace}=    Get Variable Value    ${${container_var.replace('CONTAINER', 'WORKSPACE')}}

    ${dest_path}=    Join Path    ${workspace}    ${host_file}
    Docker.Copy To Container    ${container_id}    ${host_file}    /workspace/${container_dest}

Copy File From Environment
    [Documentation]    Copy a file from the environment workspace
    [Arguments]    ${container_var}    ${container_file}    ${host_dest}
    ${container_id}=    Get Variable Value    ${${container_var}}
    Docker.Copy From Container    ${container_id}    /workspace/${container_file}    ${host_dest}
