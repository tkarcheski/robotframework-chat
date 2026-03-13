*** Settings ***
Documentation     Rust programming test suite with Docker containers
Resource          ../../resources/environments.resource
Resource          ../../resources/container_profiles.resource
Resource          ../../resources/llm_setup.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

Suite Setup       Run Keywords
...               Verify LLM Available
...               AND
...               Setup Rust Environment    RUST_STANDARD    rust-docker-suite
Suite Teardown    Teardown Environment    RUST_CONTAINER
Test Timeout      3 minutes

Test Tags         rust    docker    code-execution    compiled
