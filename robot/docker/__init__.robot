*** Settings ***
Documentation     Docker-based testing suite root configuration
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker

Suite Setup       Verify Docker Infrastructure
Suite Teardown    Cleanup Docker Infrastructure

*** Keywords ***
Verify Docker Infrastructure
    [Documentation]    Verify Docker is available and healthy
    ${available}=    Docker.Docker Is Available
    Should Be True    ${available}    Docker is not available. Please ensure Docker is installed and running.
    Log    Docker infrastructure verified and ready

Cleanup Docker Infrastructure
    [Documentation]    Cleanup any orphaned containers from previous runs
    Docker.Cleanup All Containers
    Log    Docker infrastructure cleaned up
