*** Settings ***
Documentation     Bash scripting challenges - LLM generates bash scripts executed in Docker
Resource          ../../../../resources/environments.resource
Resource          ../../../../resources/code_extraction.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String
Variables         ${CURDIR}/../variables/bash_challenges.yaml

*** Test Cases ***
LLM Generates Bash Hello World (IQ:100)
    [Documentation]    Can the LLM write a bash script that prints 'Hello World'?
    [Tags]    IQ:100    basic    tier:4    verify:robot
    Run Interpreted Challenge    ${BASH_CODE_CHALLENGES}[0]

LLM Generates Loop And Sum Script (IQ:110)
    [Documentation]    Can the LLM write a bash script that sums numbers 1 to 10?
    [Tags]    IQ:110    loops    arithmetic    tier:4    verify:robot
    Run Interpreted Challenge    ${BASH_CODE_CHALLENGES}[1]

LLM Generates Array Processing Script (IQ:120)
    [Documentation]    Can the LLM write a bash script using arrays and sorting?
    [Tags]    IQ:120    arrays    sorting    tier:4    verify:robot
    Run Interpreted Challenge    ${BASH_CODE_CHALLENGES}[2]

LLM Generates String Manipulation Script (IQ:130)
    [Documentation]    Can the LLM write a bash script with string manipulation operations?
    [Tags]    IQ:130    string-manipulation    tier:4    verify:robot
    Run Interpreted Challenge    ${BASH_CODE_CHALLENGES}[3]

LLM Generates FizzBuzz In Bash (IQ:120)
    [Documentation]    Can the LLM write FizzBuzz in bash?
    [Tags]    IQ:120    algorithm    fizzbuzz    tier:4    verify:robot
    Run Interpreted Challenge    ${BASH_CODE_CHALLENGES}[4]

*** Keywords ***
Run Interpreted Challenge
    [Documentation]    Run a YAML-defined interpreted code challenge in the bash container
    [Arguments]    ${challenge}

    ${response}=    LLM.Ask LLM    ${challenge}[prompt]
    ${code}=    Extract Code Block    ${response}    ${challenge}[language]

    # Write script to file and execute
    Write Source File In Container    BASH_CONTAINER    ${code}    /workspace/script.sh
    ${result}=    Docker.Execute In Container    ${BASH_CONTAINER}
    ...    bash /workspace/script.sh
    ...    timeout=${challenge}[timeout]

    Should Be Equal As Integers    ${result}[exit_code]    ${challenge}[expected_exit_code]
    Should Contain    ${result}[stdout]    ${challenge}[expected_output]
