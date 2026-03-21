*** Settings ***
Documentation     YAML-driven Python challenges - modular test cases loaded from YAML
Resource          ../../../resources/environments.resource
Resource          ../../../resources/code_extraction.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String
Variables         ${CURDIR}/../variables/python_challenges.yaml

*** Test Cases ***
LLM Generates Python Hello World (IQ:100)
    [Documentation]    Can the LLM write a Python script that prints 'Hello World'?
    [Tags]    IQ:100    basic    tier:4    verify:robot
    Run Python Challenge    ${PYTHON_CODE_CHALLENGES}[0]

LLM Generates List Comprehension (IQ:110)
    [Documentation]    Can the LLM write a Python script using list comprehensions?
    [Tags]    IQ:110    list-comprehension    tier:4    verify:robot
    Run Python Challenge    ${PYTHON_CODE_CHALLENGES}[1]

LLM Generates Dictionary Operations (IQ:120)
    [Documentation]    Can the LLM write a Python script that sorts a dictionary?
    [Tags]    IQ:120    dictionary    sorting    tier:4    verify:robot
    Run Python Challenge    ${PYTHON_CODE_CHALLENGES}[2]

LLM Generates Class Implementation (IQ:120)
    [Documentation]    Can the LLM write a Python class with methods?
    [Tags]    IQ:120    oop    class    tier:4    verify:robot
    Run Python Challenge    ${PYTHON_CODE_CHALLENGES}[3]

LLM Generates Python FizzBuzz (IQ:110)
    [Documentation]    Can the LLM write FizzBuzz in Python?
    [Tags]    IQ:110    algorithm    fizzbuzz    tier:4    verify:robot
    Run Python Challenge    ${PYTHON_CODE_CHALLENGES}[4]

*** Keywords ***
Run Python Challenge
    [Documentation]    Run a YAML-defined Python code challenge in the python container
    [Arguments]    ${challenge}

    ${response}=    LLM.Ask LLM    ${challenge}[prompt]
    ${code}=    Extract Code Block    ${response}    ${challenge}[language]

    ${result}=    Docker.Execute Python In Container
    ...    ${code}
    ...    container_id=${PYTHON_CONTAINER}
    ...    timeout=${challenge}[timeout]

    Should Be Equal As Integers    ${result.exit_code}    ${challenge}[expected_exit_code]
    Should Contain    ${result.stdout}    ${challenge}[expected_output]
