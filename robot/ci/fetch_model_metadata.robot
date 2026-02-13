*** Settings ***
Documentation     Research LLM model metadata using Playwright
...               Fetches model information including release dates from various sources
Library           Browser
Library           Collections
Library           OperatingSystem
Library           DateTime
Library           YAML

*** Variables ***
${OLLAMA_LIBRARY_URL}      https://ollama.com/library
${OUTPUT_FILE}           ${CURDIR}/models.yaml
${KNOWN_MODELS}          @{llama3,mistral,codellama,llama3.1}

*** Keywords ***
Research Ollama Model
    [Documentation]    Research a specific model on Ollama library page
    [Arguments]        ${model_name}

    ${url}=    Set Variable    ${OLLAMA_LIBRARY_URL}/${model_name}
    Log    Researching model: ${model_name} at ${url}

    # Navigate to model page
    Go To    ${url}
    Wait For Elements State    h1    visible    timeout=10s

    # Extract model metadata
    ${title}=    Get Text    h1
    ${description}=    Get Text    .description >> visible=false
    ${tags}=    Get Elements    .tag

    # Try to extract release date from page
    ${release_date}=    Set Variable    Unknown
    TRY
        ${date_element}=    Get Element    time[datetime]
        ${release_date}=    Get Attribute    ${date_element}    datetime
    EXCEPT
        Log    Could not extract release date for ${model_name}
    END

    # Try to extract model sizes/parameters
    ${parameters}=    Set Variable    Unknown
    TRY
        ${params_text}=    Get Text    .parameters
        ${parameters}=    Set Variable    ${params_text}
    EXCEPT
        Log    Could not extract parameters for ${model_name}
    END

    ${model_info}=    Create Dictionary
    ...    name=${model_name}
    ...    title=${title}
    ...    description=${description}
    ...    release_date=${release_date}
    ...    parameters=${parameters}
    ...    url=${url}
    ...    researched_at=${CURRENT_DATE}

    RETURN    ${model_info}

Research Hugging Face Model
    [Documentation]    Research model on Hugging Face for additional metadata
    [Arguments]        ${model_name}

    # Map Ollama names to Hugging Face equivalents
    ${hf_model}=    Set Variable If    '${model_name}' == 'llama3'    meta-llama/Meta-Llama-3-8B
    ...    ${model_name}

    ${url}=    Set Variable    https://huggingface.co/${hf_model}
    Log    Checking Hugging Face: ${url}

    TRY
        Go To    ${url}
        Wait For Elements State    h1    visible    timeout=5s

        ${title}=    Get Text    h1
        ${description}=    Get Text    [data-target="RepositoryAbout"]

        # Try to get model card metadata
        ${downloads}=    Set Variable    Unknown
        TRY
            ${downloads_text}=    Get Text    .downloads
            ${downloads}=    Set Variable    ${downloads_text}
        EXCEPT
            Log    Could not get downloads for ${model_name}
        END

        ${hf_info}=    Create Dictionary
        ...    hugging_face_url=${url}
        ...    hugging_face_title=${title}
        ...    hugging_face_description=${description}
        ...    hugging_face_downloads=${downloads}

        RETURN    ${hf_info}
    EXCEPT
        Log    Could not research Hugging Face for ${model_name}
        RETURN    ${EMPTY}
    END

Save Model Metadata
    [Documentation]    Save researched model metadata to YAML file
    [Arguments]        ${models_data}

    ${output}=    Create Dictionary
    ...    version=1.0
    ...    generated_at=${CURRENT_DATE}
    ...    models=${models_data}

    ${yaml_content}=    Dump YAML    ${output}
    Create File    ${OUTPUT_FILE}    ${yaml_content}

    Log    Model metadata saved to ${OUTPUT_FILE}

*** Test Cases ***
Research LLM Models Metadata
    [Documentation]    Research metadata for known LLM models
    [Tags]    ci    metadata    research

    # Get current date for metadata
    ${CURRENT_DATE}=    Get Current Date    result_format=%Y-%m-%d
    Set Suite Variable    ${CURRENT_DATE}

    # Initialize browser
    New Browser    chromium    headless=true
    New Page

    # Research each known model
    ${models}=    Create Dictionary

    FOR    ${model}    IN    @{KNOWN_MODELS}
        TRY
            ${model_info}=    Research Ollama Model    ${model}
            Set To Dictionary    ${models}    ${model}    ${model_info}

            # Also try Hugging Face
            ${hf_info}=    Research Hugging Face Model    ${model}
            Run Keyword If    ${hf_info} != ${EMPTY}
            ...    Set To Dictionary    ${models}[${model}]    &{hf_info}

        EXCEPT    ${error}
            Log    Error researching ${model}: ${error}    level=WARN
            # Add minimal info for failed models
            ${failed_info}=    Create Dictionary
            ...    name=${model}
            ...    error=${error}
            ...    researched_at=${CURRENT_DATE}
            Set To Dictionary    ${models}    ${model}    ${failed_info}
        END

        # Small delay to be nice to the servers
        Sleep    1s
    END

    # Close browser
    Close Browser

    # Save results
    Save Model Metadata    ${models}

    # Verify file was created
    File Should Exist    ${OUTPUT_FILE}
    Log    Successfully researched ${models.__len__()} models
