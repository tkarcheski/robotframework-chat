*** Settings ***
Documentation     SWE-bench patch generation and validation.
...               Loads SWE-bench instances, asks an LLM to generate patches,
...               applies them in Docker sandboxes, and grades the results.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           rfc.swebench_keywords.SWEBenchKeywords
Library           BuiltIn
Library           Collections

*** Variables ***
${SWEBENCH_SPLIT}       test
${SWEBENCH_SLICE}       %{SWEBENCH_SLICE=all}
${MAX_INSTANCES}        10
${DEFAULT_MODEL}        %{DEFAULT_MODEL}

*** Test Cases ***
SWE-bench Patch Generation And Validation
    [Documentation]    Iterate over SWE-bench instances, generate patches, and validate.
    ...               Per-instance failures are recorded but do not abort the loop.
    [Tags]    tier:4    verify:llm    swebench
    ${instances}=    Load SWEBench Instances    split=${SWEBENCH_SPLIT}    max_instances=${MAX_INSTANCES}    swebench_slice=${SWEBENCH_SLICE}
    ${failures}=    Create List
    FOR    ${instance}    IN    @{instances}
        ${status}=    Run Keyword And Return Status    Run SWEBench Instance    ${instance}
        IF    not ${status}
            Append To List    ${failures}    ${instance.instance_id}
        END
    END
    ${fail_count}=    Get Length    ${failures}
    IF    ${fail_count} > 0
        ${fail_ids}=    Evaluate    ", ".join($failures)
        Fail    ${fail_count} instance(s) failed: ${fail_ids}
    END

*** Keywords ***
Run SWEBench Instance
    [Arguments]    ${instance}
    LLM.Set LLM Model    ${DEFAULT_MODEL}
    ${patch}=    LLM.Ask LLM    Generate a minimal git diff patch that resolves this issue:\n\nRepository: ${instance.repo}\nBase commit: ${instance.base_commit}\n\nIssue:\n${instance.problem_statement}\n\nRespond with ONLY the unified diff patch, no explanation.
    ${result}=    Apply And Test Patch    ${instance}    ${patch}
    ${score}    ${reason}=    LLM.Grade Answer
    ...    Did this patch resolve the issue? Issue: ${instance.problem_statement}
    ...    PASS
    ...    Test result (exit_code=${result.exit_code}): ${result.test_output}
    Log SWEBench Result    ${instance.instance_id}    ${score}    ${patch}    ${reason}
    Should Be Equal As Integers    ${score}    1
