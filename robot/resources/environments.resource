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
Setup Container Environment
    [Documentation]    Generic container setup with shared workspace. Sets global variables
    ...                ${language_prefix}_CONTAINER, ${language_prefix}_WORKSPACE, and
    ...                ${language_prefix}_CONTAINER_NAME.
    [Arguments]    ${language_prefix}    ${profile}    ${suite_name}

    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    ${suite_name}-${timestamp}

    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${unique_name}
    Create Directory    ${volume_path}

    # docker-py needs each volume value to be a {"bind": ..., "mode": ...} dict;
    # a bare "/workspace:rw" str makes containers.run call str.get('bind') and no
    # container is ever created (#189).
    ${volume_spec}=    Create Dictionary    bind=/workspace    mode=rw
    ${volumes}=    Create Dictionary    ${volume_path}=${volume_spec}
    ${profile_dict}=    Set Variable    ${${profile}}
    ${full_config}=    Create Dictionary    &{profile_dict}    command=sleep infinity    volumes=${volumes}
    ${container_id}=    Docker.Create Configurable Container    ${full_config}    rfc-${unique_name}
    Should Not Be Empty    ${container_id}
    ...    ${language_prefix} Suite Setup created no container (rfc-${unique_name}); the execution suite would emit only setup noise (#189)

    Set Global Variable    ${${language_prefix}_CONTAINER}    ${container_id}
    Set Global Variable    ${${language_prefix}_WORKSPACE}    ${volume_path}
    Set Global Variable    ${${language_prefix}_CONTAINER_NAME}    rfc-${unique_name}

    Log    ${language_prefix} environment ready: ${container_id} (rfc-${unique_name})
    RETURN    ${container_id}

Setup Python Environment
    [Documentation]    Setup Python container with shared workspace for the test suite
    [Arguments]    ${profile}=PYTHON_STANDARD    ${suite_name}=python-suite
    ${container_id}=    Setup Container Environment    PYTHON    ${profile}    ${suite_name}
    RETURN    ${container_id}

Setup Node Environment
    [Documentation]    Setup Node.js container for JavaScript/TypeScript testing
    [Arguments]    ${profile}=NODE_STANDARD    ${suite_name}=node-suite
    ${container_id}=    Setup Container Environment    NODE    ${profile}    ${suite_name}
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
    ${profile_dict}=    Set Variable    ${${profile}}
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
    ${container_id}=    Setup Container Environment    C    ${profile}    ${suite_name}
    RETURN    ${container_id}

Setup Rust Environment
    [Documentation]    Setup Rust container for Rust code compilation and execution
    [Arguments]    ${profile}=RUST_STANDARD    ${suite_name}=rust-suite
    ${container_id}=    Setup Container Environment    RUST    ${profile}    ${suite_name}
    RETURN    ${container_id}

Setup Bash Environment
    [Documentation]    Setup Bash container for bash script execution
    [Arguments]    ${profile}=BASH_STANDARD    ${suite_name}=bash-suite
    ${container_id}=    Setup Container Environment    BASH    ${profile}    ${suite_name}
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
