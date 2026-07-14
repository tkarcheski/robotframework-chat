*** Settings ***
Documentation     Context Window Stress Testing
...
...               Measures LLM degradation as context fills up.
...               Embeds a critical fact (needle) in increasing amounts of
...               filler content at 25%, 50%, 75%, 95% fill levels and at
...               three positions (start, middle, end) within the context.
...
...               Tests the "lost in the middle" effect — how position and
...               volume of surrounding text degrade retrieval accuracy.
...               Floor assertion: model must pass at 25% fill, end position.
...               Higher levels emit metrics for analysis but don't hard-fail.

Resource          ../context_window.resource
Variables         ../variables/needles.yaml

Default Tags      context_window    tier:2    verify:llm

Test Timeout      100 minutes

Suite Setup       Set Suite Variable    ${CONTEXT_WINDOW}    ${CONTEXT_WINDOW}
Test Tags         axis:model

*** Variables ***
${CONTEXT_WINDOW}    8192

*** Test Cases ***
Needle Retrieval Floor Test — 25% Fill, End Position
    [Documentation]    Floor assertion: model must retrieve needle at low fill.
    ...                This is the golden path with minimal context pollution.
    ...                If this fails, something is fundamentally wrong.
    [Tags]    tier:2    verify:llm    floor
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    25    end    ${CONTEXT_WINDOW}
        Assert Needle Recalled    ${result}
    END

Needle Retrieval at 50% Fill — End Position
    [Documentation]    Moderate fill: baseline degradation test.
    ...                Emits metrics but does not hard-assert.
    [Tags]    tier:2    verify:llm    degradation
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    50    end    ${CONTEXT_WINDOW}
    END

Needle Retrieval at 75% Fill — End Position
    [Documentation]    High fill: expect increasing retrieval difficulty.
    [Tags]    tier:2    verify:llm    degradation
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    75    end    ${CONTEXT_WINDOW}
    END

Needle Retrieval at 95% Fill — End Position
    [Documentation]    Extreme fill: stress test at near-maximum context.
    [Tags]    tier:2    verify:llm    extreme
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    95    end    ${CONTEXT_WINDOW}
    END

Needle Position Effect — 50% Fill, Start Position
    [Documentation]    Test positional effect: needle at start of context.
    ...                Baseline for "lost in the middle" comparison.
    [Tags]    tier:2    verify:llm    position
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    50    start    ${CONTEXT_WINDOW}
    END

Needle Position Effect — 50% Fill, Middle Position
    [Documentation]    Test positional effect: needle in middle of context.
    ...                Research suggests degradation here in long contexts.
    [Tags]    tier:2    verify:llm    position
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    50    middle    ${CONTEXT_WINDOW}
    END

Needle Position Effect — 75% Fill, Start Position
    [Documentation]    High fill + start position: control for position study.
    [Tags]    tier:2    verify:llm    position
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    75    start    ${CONTEXT_WINDOW}
    END

Needle Position Effect — 75% Fill, Middle Position
    [Documentation]    High fill + middle position: expect worst-case degradation.
    [Tags]    tier:2    verify:llm    position
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    75    middle    ${CONTEXT_WINDOW}
    END

Needle Position Effect — 75% Fill, End Position
    [Documentation]    High fill + end position: recency effect baseline.
    [Tags]    tier:2    verify:llm    position
    FOR    ${case}    IN    @{NEEDLE_CASES}
        ${result}=    Probe Needle At Fill Level    ${case}    75    end    ${CONTEXT_WINDOW}
    END
