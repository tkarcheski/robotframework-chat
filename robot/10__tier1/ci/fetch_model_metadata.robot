*** Settings ***
Documentation     Research LLM model metadata using Playwright.
...               Fetches model information including release dates from
...               various sources and writes the result to YAML.
Library           Collections
Library           OperatingSystem
Library           DateTime
Library           rfc.model_metadata_keywords.ModelMetadataKeywords    WITH NAME    Metadata
Test Tags         browser

*** Variables ***
${OUTPUT_FILE}           ${CURDIR}/models.yaml
@{KNOWN_MODELS}          llama3    mistral    codellama    llama3.1

*** Test Cases ***
Research LLM Models Metadata
    [Documentation]    Can the system scrape and save metadata for known LLM models (llama3, mistral, codellama)?
    [Tags]    ci    metadata    research    tier:1    verify:robot
    ${today}=    Get Current Date    result_format=%Y-%m-%d
    ${models}=    Metadata.Research Models Metadata    ${KNOWN_MODELS}
    Metadata.Save Model Metadata Yaml    ${models}    ${OUTPUT_FILE}    generated_at=${today}
    File Should Exist    ${OUTPUT_FILE}
    Log    Successfully researched ${models.__len__()} models
