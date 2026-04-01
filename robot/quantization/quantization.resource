*** Settings ***
Documentation     Shared keywords for quantization degradation tests.
Library           rfc.quantization_keywords.QuantizationKeywords    WITH NAME    Quant
Variables         ${CURDIR}/variables/quant_tests.yaml

*** Keywords ***
Discover And Validate Variants
    [Documentation]    Discover Q4/Q8 variants and skip the test if both are not available.
    ${variants}=    Quant.Discover Quantization Variants    ${BASE_MODEL}
    IF    not ${variants}[both_available]
        Skip    Both Q4 and Q8 variants not available for ${BASE_MODEL}
    END
    RETURN    ${variants}

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
