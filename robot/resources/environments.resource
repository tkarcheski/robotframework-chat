*** Settings ***
Documentation     Reusable test environment setups for code execution
Resource          container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           OperatingSystem
Library           String

*** Variables ***
${SHARED_VOLUME_BASE}    /tmp/rfc-environments
${DEFAULT_TIMEOUT}       30

*** Keywords ***
Setup Python Environment
    [Documentation]    Setup Python container with shared workspace for the test suite
    [Arguments]    ${profile}=PYTHON_STANDARD    ${suite_name}=python-suite
    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${suite_name}
    Create Directory    ${volume_path}

    ${volumes}=    Create Dictionary    ${volume_path}=/workspace:rw
    ${container_id}=    Create Container From Profile    ${profile}
    ...    container_name=rfc-${suite_name}
    ...    custom_volumes=${volumes}

    Set Suite Variable    ${PYTHON_CONTAINER}    ${container_id}
    Set Suite Variable    ${PYTHON_WORKSPACE}    ${volume_path}

    Log    Python environment ready: ${container_id}
    RETURN    ${container_id}

Setup Node Environment
    [Documentation]    Setup Node.js container for JavaScript/TypeScript testing
    [Arguments]    ${profile}=NODE_STANDARD    ${suite_name}=node-suite
    ${volume_path}=    Set Variable    ${SHARED_VOLUME_BASE}/${suite_name}
    Create Directory    ${volume_path}

    ${volumes}=    Create Dictionary    ${volume_path}=/workspace:rw
    ${container_id}=    Create Container From Profile    ${profile}
    ...    container_name=rfc-${suite_name}
    ...    custom_volumes=${volumes}

    Set Suite Variable    ${NODE_CONTAINER}    ${container_id}
    Set Suite Variable    ${NODE_WORKSPACE}    ${volume_path}

    Log    Node environment ready: ${container_id}
    RETURN    ${container_id}

Setup Shell Environment
    [Documentation]    Setup shell container for terminal/command testing
    [Arguments]    ${profile}=ALPINE_SHELL    ${suite_name}=shell-suite
    ${container_id}=    Create Container From Profile    ${profile}
    ...    container_name=rfc-${suite_name}

    # Install common tools
    Docker.Execute In Container    ${container_id}    apk add --no-cache bash coreutils

    Set Suite Variable    ${SHELL_CONTAINER}    ${container_id}

    Log    Shell environment ready: ${container_id}
    RETURN    ${container_id}

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
