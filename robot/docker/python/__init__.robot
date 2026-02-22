*** Settings ***
Documentation     Python code execution test suite with Docker containers
Resource          ../../resources/environments.resource
Resource          ../../resources/container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

Suite Setup       Setup Python Environment    PYTHON_STANDARD    python-docker-suite
Suite Teardown    Teardown Environment    PYTHON_CONTAINER
Test Timeout      2 minutes

Test Tags         python    docker    code-execution
