*** Settings ***
Documentation     Terminal/shell simulation test suite
Resource          ../../resources/environments.resource
Resource          ../../resources/container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String
Library           Process

Suite Setup       Run Keywords
...               Cleanup Any Existing Shell Containers
...               AND
...               Setup Shell Environment    ALPINE_SHELL    shell-docker-suite
Suite Teardown    Teardown Environment    SHELL_CONTAINER
Test Timeout      90 seconds

Test Tags         shell    terminal    docker

*** Keywords ***
Cleanup Any Existing Shell Containers
    [Documentation]    Remove any existing shell-docker-suite containers to prevent conflicts
    Run Keyword And Ignore Error    Docker.Stop Container By Name    rfc-shell-docker-suite
    # Also cleanup any timestamped variations
    ${result}=    Run Process    docker ps -aq --filter "name=shell-docker-suite" --format "{{.ID}}"    shell=True
    Run Keyword If    '${result.stdout}' != ''    Run Process    docker rm -f ${result.stdout}    shell=True
