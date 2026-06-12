*** Settings ***
Documentation     IFEval benchmark — official google/IFEval dataset subset.
...
...               Runs a committed 50-item subset of the google/IFEval
...               instruction-following benchmark (Hugging Face, Apache-2.0),
...               imported statically via scripts/import_hf_benchmark.py.
...               Each item sends the original benchmark prompt to the LLM and
...               verifies every instruction with deterministic Python
...               checkers (official IFEval semantics, strict prompt-level
...               accuracy) — no LLM judge is involved.
...
...               ${IFEVAL_HF_LIMIT} caps how many items run (default 10 to
...               keep CI runtime bounded); override with
...               --variable IFEVAL_HF_LIMIT:50 for the full committed subset.

Resource          ifeval.resource
Library           Collections
Variables         ${CURDIR}/variables/ifeval_hf.yaml

Default Tags      ifeval    ifeval_hf    benchmark    tier:1    verify:python

*** Variables ***
${IFEVAL_HF_LIMIT}    10

*** Test Cases ***
IFEval HF Benchmark Subset
    [Documentation]    Strict prompt-level accuracy over the committed google/IFEval subset.
    [Timeout]    30 minutes
    ${count}=    Get Length    ${IFEVAL_HF}
    ${end}=    Evaluate    min(int($IFEVAL_HF_LIMIT), $count)
    ${items}=    Get Slice From List    ${IFEVAL_HF}    0    ${end}
    FOR    ${item}    IN    @{items}
        ${result}=    Run IFEval Dataset Item    ${item}
        Run Keyword And Continue On Failure    Assert IFEval Passed    ${result}
    END
