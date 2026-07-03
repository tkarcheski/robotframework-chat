*** Settings ***
Documentation     Shared keywords for quantization degradation tests.
Library           rfc.quantization_keywords.QuantizationKeywords    WITH NAME    Quant
Library           OperatingSystem
Variables         ${CURDIR}/variables/quant_tests.yaml

*** Variables ***
# Override on the CLI with --variable BASE_MODEL:xxx.
# When empty, the full DEFAULT_MODEL env var is used (e.g. "mistral:7b-instruct-q4_K_M").
# discover_quantization_variants strips the quant tag internally to match by stem.
${BASE_MODEL}     ${EMPTY}

*** Keywords ***
Discover And Validate Variants
    [Documentation]    Discover Q4/Q8 variants and skip the test if both are not available.
    ${base}=    Resolve Base Model
    ${variants}=    Quant.Discover Quantization Variants    ${base}
    IF    not ${variants}[both_available]
        Skip    Both Q4 and Q8 variants not available for ${base}
    END
    RETURN    ${variants}

Resolve Base Model
    [Documentation]    Return BASE_MODEL if set, otherwise the full DEFAULT_MODEL env var.
    ...                The Python discovery keyword handles stem extraction internally.
    IF    "${BASE_MODEL}" != ""
        RETURN    ${BASE_MODEL}
    END
    ${default_model}=    Get Environment Variable    DEFAULT_MODEL
    RETURN    ${default_model}

Run Degradation Comparison
    [Documentation]    Run a quantization comparison for a prompt set and assert acceptable degradation.
    [Arguments]    ${variants}    ${prompts}    ${max_degradation}=${MAX_DEGRADATION_PCT}
    ${result}=    Quant.Run Quantization Comparison
    ...    ${variants}[q4_model]
    ...    ${variants}[q8_model]
    ...    ${prompts}
    Quant.Log Quantization Delta    ${result}
    Quant.Assert Acceptable Degradation    ${result}    max_degradation_pct=${max_degradation}
    Log    Q4=${result}[q4_avg] Q8=${result}[q8_avg] delta=${result}[delta] degradation=${result}[degradation_pct]%
