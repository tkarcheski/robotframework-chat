*** Settings ***
Documentation     Docker-based testing suite root configuration
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker

# RFC-008 A1: every docker suite runs LLM-generated code in a container and
# discriminates the MODEL (the harness and prompt are held constant). Set at the
# directory root so it cascades to every ``docker/*/tests/*.robot`` suite.
Test Tags         axis:model

Suite Setup       Run Keywords
...               Verify Docker Setup
...               AND
...               Cleanup Docker Infrastructure
Suite Teardown    Cleanup Docker Infrastructure

*** Keywords ***
Verify Docker Setup
    [Documentation]    Verify Docker CLI is installed and daemon is running.
    ...    Fails the suite with a diagnostic message if any check fails.
    ${result}=    Docker.Check Docker Setup
    IF    not ${result}[docker_cli]
        Skip    Docker CLI is not installed or not on PATH. Install Docker: https://docs.docker.com/get-docker/
    END
    IF    not ${result}[daemon_running]
        Skip    Docker daemon is not running. Please start Docker and try again.
    END
    Log    Docker setup OK: v${result}[docker_version] (API v${result}[api_version]) at ${result}[docker_cli_path]

Cleanup Docker Infrastructure
    [Documentation]    Cleanup any orphaned containers from previous runs
    Docker.Cleanup All Containers
    Log    Docker infrastructure cleaned up
