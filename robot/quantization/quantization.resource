*** Settings ***
Documentation     Shared keywords for quantization degradation tests.
Library           rfc.quantization_keywords.QuantizationKeywords    WITH NAME    Quant
Library           OperatingSystem
Variables         ${CURDIR}/variables/quant_tests.yaml

*** Variables ***
# Derived from DEFAULT_MODEL env var; strips the tag portion (e.g. "phi4:14b" → "phi4").
# Override on the CLI with --variable BASE_MODEL:xxx.
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
    [Documentation]    Determine the base model name from BASE_MODEL variable or DEFAULT_MODEL env var.
    IF    "${BASE_MODEL}" != ""
        RETURN    ${BASE_MODEL}
    END
    ${default_model}=    Get Environment Variable    DEFAULT_MODEL    default=phi4:14b
    # Strip tag (everything after the first colon) to get the family name.
    ${parts}=    Evaluate    "${default_model}".split(":")[0]
    RETURN    ${parts}

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
