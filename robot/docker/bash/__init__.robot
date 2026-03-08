*** Settings ***
Documentation     Bash scripting test suite with Docker containers
Resource          ../../resources/environments.resource
Resource          ../../resources/container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

Suite Setup       Setup Bash Environment    BASH_STANDARD    bash-docker-suite
Suite Teardown    Teardown Environment    BASH_CONTAINER
Test Timeout      2 minutes

Test Tags         bash    docker    code-execution
