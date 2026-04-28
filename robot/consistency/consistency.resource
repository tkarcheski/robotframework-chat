*** Settings ***
Documentation     Shared keywords for temperature & sampling consistency tests.
Library           rfc.consistency_keywords.ConsistencyKeywords    WITH NAME    Consistency
Variables         ${CURDIR}/variables/consistency_prompts.yaml

*** Keywords ***
Run Determinism Check
    [Documentation]    Replay a prompt N times at temperature=0 and assert
    ...                every response is byte-identical. Logs metrics for
    ...                the SQL archive even on failure (so failures are visible
    ...                in dashboards).
    [Arguments]    ${prompt}    ${n}=${N_RUNS}    ${seed}=${DETERMINISM_SEED}
    ${responses}=    Consistency.Run Prompt N Times
    ...    ${prompt}
    ...    n=${n}
    ...    temperature=${DETERMINISM_TEMP}
    ...    seed=${seed}
    ${result}=    Consistency.Assert All Identical    ${responses}
    # Log metrics BEFORE assertion so failures are archived (RFC_DATA always emitted)
    Consistency.Log Consistency Metrics
    ...    ${result}
    ...    kind=determinism
    ...    temperature=${DETERMINISM_TEMP}
    # Now assert — RFC data is already logged
    IF    ${result}[error_message]
        FAIL    ${result}[error_message]
    END
    Log    Determinism: match_rate=${result}[match_rate] unique=${result}[unique_count]
    RETURN    ${result}

Run Variance Check
    [Documentation]    Replay a prompt N times at temperature=0.7 and measure
    ...                pairwise semantic similarity via the LLM judge. Asserts
    ...                that mean and minimum pair stay above the configured
    ...                floors.
    [Arguments]    ${prompt}    ${n}=${N_RUNS}
    ...    ${mean_floor}=${VARIANCE_MEAN_FLOOR}
    ...    ${min_pair_floor}=${VARIANCE_MIN_PAIR_FLOOR}
    ${responses}=    Consistency.Run Prompt N Times
    ...    ${prompt}
    ...    n=${n}
    ...    temperature=${VARIANCE_TEMP}
    ${result}=    Consistency.Measure Semantic Variance    ${responses}    ${prompt}
    Consistency.Log Consistency Metrics
    ...    ${result}
    ...    kind=variance
    ...    temperature=${VARIANCE_TEMP}
    Consistency.Assert Variance Within Threshold
    ...    ${result}
    ...    mean_floor=${mean_floor}
    ...    min_pair_floor=${min_pair_floor}
    Log    Variance: mean=${result}[mean_similarity] min=${result}[min_pairwise]
    RETURN    ${result}
