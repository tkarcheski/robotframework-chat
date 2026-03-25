*** Settings ***
Documentation     SWE-bench patch generation and validation.
...               Loads SWE-bench instances, asks an LLM to generate patches,
...               applies them in Docker sandboxes, and grades the results.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           rfc.swebench_keywords.SWEBenchKeywords
Library           Collections

*** Variables ***
${SWEBENCH_SPLIT}       test
${MAX_INSTANCES}        10

*** Test Cases ***
SWE-bench Patch Generation And Validation
    [Documentation]    Iterate over SWE-bench instances, generate patches, and validate.
    [Tags]    tier:4    verify:llm    swebench
    ${instances}=    Load SWEBench Instances    split=${SWEBENCH_SPLIT}    max_instances=${MAX_INSTANCES}
    FOR    ${instance}    IN    @{instances}
        Run SWEBench Instance    ${instance}
    END

*** Keywords ***
Run SWEBench Instance
    [Arguments]    ${instance}
    ${patch}=    LLM.Ask LLM    Generate a minimal git diff patch that resolves this issue:\n\nRepository: ${instance.repo}\nBase commit: ${instance.base_commit}\n\nIssue:\n${instance.problem_statement}\n\nRespond with ONLY the unified diff patch, no explanation.
    ${result}=    Apply And Test Patch    ${instance}    ${patch}
    ${score}    ${reason}=    LLM.Grade Answer
    ...    Did this patch resolve the issue? Issue: ${instance.problem_statement}
    ...    PASS
    ...    Test result (exit_code=${result.exit_code}): ${result.test_output}
    Log SWEBench Result    ${instance.instance_id}    ${score}    ${patch}    ${reason}
    Should Be Equal As Integers    ${score}    1
