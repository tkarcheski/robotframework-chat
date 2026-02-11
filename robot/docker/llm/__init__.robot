*** Settings ***
Documentation     LLM-in-Docker test suite for multi-model testing
Resource          ../../resources/llm_containers.resource

Suite Setup       Verify Docker And Start Infrastructure
Suite Teardown    Cleanup Infrastructure

*** Keywords ***
Verify Docker And Start Infrastructure
    [Documentation]    Verify Docker is available
    Verify Docker Available
    Log    Docker infrastructure ready for LLM testing

Cleanup Infrastructure
    [Documentation]    Cleanup any LLM containers
    Run Keyword And Ignore Error    Stop LLM Container
    Log    LLM infrastructure cleaned up
