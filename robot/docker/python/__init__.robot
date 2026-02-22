*** Settings ***
Documentation     Python code execution test suite with Docker containers
Resource          ../../resources/environments.resource
Resource          ../../resources/container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

Suite Setup       Run Keywords
...               Cleanup Any Existing Python Containers
...               AND
...               Setup Python Environment    PYTHON_STANDARD    python-docker-suite
Suite Teardown    Teardown Environment    PYTHON_CONTAINER
Test Timeout      2 minutes

Test Tags         python    docker    code-execution

*** Keywords ***
Cleanup Any Existing Python Containers
    [Documentation]    Remove any existing python-docker-suite containers to prevent conflicts
    Run Keyword And Ignore Error    Docker.Stop Container By Name    rfc-python-docker-suite
    # Also cleanup any timestamped variations
    ${result}=    Run Process    docker ps -aq --filter "name=python-docker-suite" --format "{{.ID}}"    shell=True
    Run Keyword If    '${result.stdout}' != ''    Run Process    docker rm -f ${result.stdout}    shell=True
