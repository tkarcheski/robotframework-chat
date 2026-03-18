*** Settings ***
Documentation     C programming challenges - LLM generates C code compiled and executed in Docker
Resource          ../../../resources/environments.resource
Resource          ../../../resources/code_extraction.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String
Variables         ${CURDIR}/../variables/c_challenges.yaml

*** Test Cases ***
LLM Generates C Hello World (IQ:100)
    [Documentation]    Can the LLM write a C program that prints 'Hello World'?
    [Tags]    IQ:100    basic    tier:4    verify:robot
    Run Compiled Challenge    ${C_CODE_CHALLENGES}[0]

LLM Generates C Factorial Function (IQ:120)
    [Documentation]    Can the LLM write a C program with an iterative factorial function?
    [Tags]    IQ:120    algorithm    function-generation    tier:4    verify:robot
    Run Compiled Challenge    ${C_CODE_CHALLENGES}[1]

LLM Generates C String Reverse (IQ:120)
    [Documentation]    Can the LLM write a C program that reverses a string in-place?
    [Tags]    IQ:120    string-manipulation    tier:4    verify:robot
    Run Compiled Challenge    ${C_CODE_CHALLENGES}[2]

LLM Generates C Bubble Sort (IQ:130)
    [Documentation]    Can the LLM write a C program implementing bubble sort?
    [Tags]    IQ:130    algorithm    sorting    tier:4    verify:robot
    Run Compiled Challenge    ${C_CODE_CHALLENGES}[3]

LLM Generates C FizzBuzz (IQ:110)
    [Documentation]    Can the LLM write FizzBuzz in C?
    [Tags]    IQ:110    algorithm    fizzbuzz    tier:4    verify:robot
    Run Compiled Challenge    ${C_CODE_CHALLENGES}[4]

*** Keywords ***
Run Compiled Challenge
    [Documentation]    Run a YAML-defined compiled code challenge
    [Arguments]    ${challenge}

    ${response}=    LLM.Ask LLM    ${challenge}[prompt]
    ${code}=    Extract Code Block    ${response}    ${challenge}[language]

    ${result}=    Compile And Run In Container
    ...    C_CONTAINER    ${code}
    ...    ${challenge}[source_file]    ${challenge}[compile_command]
    ...    ${challenge}[run_command]    timeout=${challenge}[timeout]

    Should Be Equal As Integers    ${result}[exit_code]    ${challenge}[expected_exit_code]
    Should Contain    ${result}[stdout]    ${challenge}[expected_output]
