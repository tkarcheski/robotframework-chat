*** Settings ***
Documentation     Shared keywords for token output benchmarking.
...
...               Provides the ``Run Token Benchmark`` keyword that configures
...               LLM parameters, sends a prompt, validates the response meets
...               an 80 %% completion threshold, and emits benchmark metrics.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           rfc.benchmark_keywords.BenchmarkKeywords    WITH NAME    Benchmark
Resource          ../../resources/llm_setup.resource

*** Keywords ***
Run Token Benchmark
    [Documentation]    Send a prompt with the given max_tokens budget and validate completion.
    ...    Sets num_ctx to max_tokens * 2 + 512 to ensure room for prompt + output.
    ...    Fails if the model produces fewer than 80% of requested tokens.
    [Arguments]    ${max_tokens}    ${prompt}
    ${num_ctx}=    Evaluate    int(${max_tokens}) * 2 + 512
    LLM.Set LLM Parameters    temperature=0.0    max_tokens=${max_tokens}    num_ctx=${num_ctx}
    ${response}=    LLM.Ask LLM    ${prompt}
    Should Not Be Empty    ${response}    Model returned empty response at ${max_tokens} tokens
    ${estimated}=    Benchmark.Estimate Response Tokens    ${response}
    Log    Estimated ${estimated} tokens from ${max_tokens} max_tokens request
    ${ratio}=    Evaluate    ${estimated} / int(${max_tokens})
    Should Be True    ${ratio} >= 0.8    Model produced only ${estimated} of ${max_tokens} tokens (ratio=${ratio})
