*** Settings ***
Documentation     LLM container configurations for testing LLMs in Docker
Resource          container_profiles.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           RequestsLibrary
Library           Collections
Library           String

*** Variables ***
${OLLAMA_PORT}          11434
${OLLAMA_HOST}          localhost
${OLLAMA_BASE_URL}      http://${OLLAMA_HOST}:${OLLAMA_PORT}
${DEFAULT_LLM_TIMEOUT}  120

# Model configurations
&{LLAMA3_CONFIG}        model=llama3    endpoint=${OLLAMA_BASE_URL}    timeout=60
&{MISTRAL_CONFIG}       model=mistral   endpoint=${OLLAMA_BASE_URL}    timeout=60
&{CODELLAMA_CONFIG}     model=codellama endpoint=${OLLAMA_BASE_URL}    timeout=90
&{LLAMA3.1_CONFIG}      model=llama3.1  endpoint=${OLLAMA_BASE_URL}    timeout=60

*** Keywords ***
Start LLM Container
    [Documentation]    Start Ollama container with specified resources on an available port
    [Arguments]    ${profile}=OLLAMA_CPU    ${container_name}=rfc-ollama    ${pull_models}=llama3

    # Find an available port to avoid conflicts with local Ollama
    ${available_port}=    Docker.Find Available Port    11434    11500
    Log    Using port ${available_port} for Ollama container

    # Update global variables with actual port
    Set Global Variable    ${OLLAMA_PORT}    ${available_port}
    Set Global Variable    ${OLLAMA_BASE_URL}    http://${OLLAMA_HOST}:${available_port}

    # Create port mapping for container (Ollama always listens on 11434 inside container)
    # Docker SDK format: {'11434/tcp': host_port}
    ${container_port_key}=    Set Variable    11434/tcp
    ${port_mapping}=    Create Dictionary    ${container_port_key}=${available_port}

    # Get base profile and add dynamic port configuration
    ${profile_dict}=    Get Variable Value    ${${profile}}
    ${full_config}=    Create Dictionary    &{profile_dict}    ports=${port_mapping}    auto_remove=False

    # Create container with dynamic port
    ${container_id}=    Docker.Create Configurable Container    ${full_config}    ${container_name}
    Set Global Variable    ${LLM_CONTAINER_ID}    ${container_id}
    Set Global Variable    ${LLM_ENDPOINT}    ${OLLAMA_BASE_URL}

    # Wait for Ollama API to be ready
    Wait For Ollama Ready    ${container_id}    timeout=60

    # Pull requested models
    ${model_list}=    Split String    ${pull_models}    ,
    ${first_model}=    Get From List    ${model_list}    0
    FOR    ${model}    IN    @{model_list}
        Pull LLM Model    ${container_id}    ${model}
    END

    # Configure LLM keywords to use container endpoint
    LLM.Set LLM Endpoint    ${OLLAMA_BASE_URL}
    LLM.Set LLM Model    ${first_model}

    Log    LLM container started: ${container_id} on port ${available_port} with models: ${pull_models}
    RETURN    ${container_id}

Stop LLM Container
    [Documentation]    Stop and remove LLM container
    Docker.Stop Container    ${LLM_CONTAINER_ID}
    Set Global Variable    ${LLM_CONTAINER_ID}    ${None}
    Log    LLM container stopped

Wait For Ollama Ready
    [Documentation]    Wait for Ollama API to be ready
    [Arguments]    ${container_id}    ${timeout}=60

    # Wait for API to respond (Ollama takes time to start)
    Wait Until Keyword Succeeds    ${timeout}s    2s
    ...    Check Ollama Health

Check Ollama Health
    [Documentation]    Check if Ollama API is responding
    ${response}=    GET    ${OLLAMA_BASE_URL}/api/tags    timeout=5
    Should Be Equal As Integers    ${response.status_code}    200

Pull LLM Model
    [Documentation]    Pull a model into the running Ollama container
    [Arguments]    ${container_id}    ${model_name}
    Log    Pulling model: ${model_name}
    ${result}=    Docker.Execute In Container    ${container_id}
    ...    ollama pull ${model_name}
    ...    timeout=300
    Should Be Equal As Integers    ${result}[exit_code]    0
    Log    Model ${model_name} pulled successfully

Switch LLM Model
    [Documentation]    Switch to a different model
    [Arguments]    ${model_name}
    LLM.Set LLM Model    ${model_name}
    Log    Switched to model: ${model_name}

Ask Multiple LLMs
    [Documentation]    Send same prompt to multiple models and collect responses
    [Arguments]    ${prompt}    ${models}=llama3    ${timeout}=60

    ${model_list}=    Split String    ${models}    ,
    ${responses}=    Create Dictionary

    FOR    ${model}    IN    @{model_list}
        Switch LLM Model    ${model}
        ${response}=    LLM.Ask LLM    ${prompt}
        Set To Dictionary    ${responses}    ${model}    ${response}
        Log    ${model} response received (${{len('${response}')}} chars)
    END

    RETURN    ${responses}

Run Multi-Model Comparison
    [Documentation]    Run same prompt across models and compare results
    [Arguments]    ${prompt}    ${models}=llama3,codellama    ${timeout}=60

    # Get responses from all models
    ${responses}=    Ask Multiple LLMs    ${prompt}    ${models}    ${timeout}

    # Grade each response
    ${scores}=    Create Dictionary
    ${reasons}=    Create Dictionary

    FOR    ${model}    IN    @{responses.keys()}
        ${score}    ${reason}=    LLM.Grade Answer    ${prompt}    good response    ${responses}[${model}]
        Set To Dictionary    ${scores}    ${model}    ${score}
        Set To Dictionary    ${reasons}    ${model}    ${reason}
    END

    # Return comparison results
    ${comparison}=    Create Dictionary
    ...    responses=${responses}
    ...    scores=${scores}
    ...    reasons=${reasons}
    ...    best_model=${None}

    # Find best model
    ${best_score}=    Set Variable    -1
    FOR    ${model}    IN    @{scores.keys()}
        ${score}=    Get From Dictionary    ${scores}    ${model}
        ${score_int}=    Convert To Integer    ${score}
        Run Keyword If    ${score_int} > ${best_score}
        ...    Set To Dictionary    ${comparison}    best_model    ${model}
        ${best_score}=    Set Variable If    ${score_int} > ${best_score}    ${score_int}    ${best_score}
    END

    RETURN    ${comparison}

Get Container Metrics During Test
    [Documentation]    Log container resource usage
    [Arguments]    ${container_id}=${LLM_CONTAINER_ID}
    ${metrics}=    Docker.Get Container Metrics    ${container_id}
    Log    CPU: ${metrics}[cpu_percent]% | Memory: ${metrics}[memory_usage_mb]/${metrics}[memory_limit_mb] MB (${metrics}[memory_percent]%)
    RETURN    ${metrics}
