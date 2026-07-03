*** Settings ***
Documentation     Terminal/shell simulation test suite
Resource          ../../../resources/environments.resource
Resource          ../../../resources/container_profiles.resource
Resource          ../../../resources/llm_setup.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String

Suite Setup       Run Keywords
...               Verify LLM Available
...               AND
...               Setup Shell Environment    ALPINE_SHELL    shell-docker-suite
Suite Teardown    Teardown Environment    SHELL_CONTAINER
Test Timeout      90 seconds

Test Tags         shell    terminal    docker
