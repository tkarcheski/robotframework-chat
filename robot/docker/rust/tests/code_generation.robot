*** Settings ***
Documentation     Rust programming challenges - LLM generates Rust code compiled and executed in Docker
Resource          ../../../resources/environments.resource
Resource          ../../../resources/code_extraction.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String
Variables         ${CURDIR}/../variables/rust_challenges.yaml

*** Test Cases ***
LLM Generates Rust Hello World (IQ:100)
    [Documentation]    Can the LLM write a Rust program that prints 'Hello World'?
    [Tags]    IQ:100    basic    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[0]

LLM Generates Rust Factorial Function (IQ:120)
    [Documentation]    Can the LLM write a Rust program with an iterative factorial function?
    [Tags]    IQ:120    algorithm    function-generation    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[1]

LLM Generates Rust Ownership Example (IQ:130)
    [Documentation]    Can the LLM write a Rust program demonstrating ownership and borrowing?
    [Tags]    IQ:130    ownership    borrowing    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[2]

LLM Generates Rust Pattern Matching (IQ:120)
    [Documentation]    Can the LLM write a Rust program using match expressions?
    [Tags]    IQ:120    pattern-matching    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[3]

LLM Generates Rust FizzBuzz (IQ:110)
    [Documentation]    Can the LLM write FizzBuzz in Rust?
    [Tags]    IQ:110    algorithm    fizzbuzz    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[4]

*** Keywords ***
Run Compiled Challenge
    [Documentation]    Run a YAML-defined compiled code challenge
    [Arguments]    ${challenge}

    ${response}=    LLM.Ask LLM    ${challenge}[prompt]
    ${code}=    Extract Code Block    ${response}    ${challenge}[language]

    ${result}=    Compile And Run In Container
    ...    RUST_CONTAINER    ${code}
    ...    ${challenge}[source_file]    ${challenge}[compile_command]
    ...    ${challenge}[run_command]    timeout=${challenge}[timeout]

    Should Be Equal As Integers    ${result}[exit_code]    ${challenge}[expected_exit_code]
    Should Contain    ${result}[stdout]    ${challenge}[expected_output]
