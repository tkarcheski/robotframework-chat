*** Settings ***
Documentation     LLM-in-Docker test suite for multi-model testing
Resource          ../../resources/llm_containers.resource

Suite Setup       Start LLM Suite
Suite Teardown    Cleanup LLM Suite

*** Variables ***
${OLLAMA_CONTAINER_NAME}    rfc-ollama-${SUITE_NAME}

*** Keywords ***
Start LLM Suite
    [Documentation]    Start LLM container with dynamic port allocation
    Verify Docker Available
    
    # Generate unique container name using timestamp
    ${timestamp}=    Evaluate    int(__import__('time').time())
    ${unique_name}=    Set Variable    rfc-ollama-${timestamp}
    Set Suite Variable    ${OLLAMA_CONTAINER_NAME}    ${unique_name}
    
    # Start fresh container with unique name
    ${container}=    Start LLM Container    OLLAMA_CPU    ${OLLAMA_CONTAINER_NAME}    llama3
    Log    LLM suite started with container: ${container} (${OLLAMA_CONTAINER_NAME}) on port ${OLLAMA_PORT}

Cleanup LLM Suite
    [Documentation]    Cleanup LLM container
    Run Keyword And Ignore Error    Stop LLM Container
    # Also try to clean up by name in case ID wasn't set
    Run Keyword And Ignore Error    Docker.Stop Container By Name    ${OLLAMA_CONTAINER_NAME}
    Log    LLM suite cleaned up
