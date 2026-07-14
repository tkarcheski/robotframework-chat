*** Settings ***
Documentation     Code review benchmark — Devign defect detection subset.
...
...               Runs a committed 50-item balanced subset of the CodeXGLUE
...               defect-detection benchmark (google/code_x_glue_cc_defect_detection,
...               Hugging Face, C-UDA-1.0), imported statically via
...               scripts/import_hf_benchmark.py.  Each item shows the LLM a
...               real C function from FFmpeg/QEMU; the model answers YES/NO
...               (vulnerable or not) on the first line and the verdict is
...               extracted deterministically — no LLM judge is involved.
...
...               Grading is accuracy over the sampled items: the task is
...               binary with a class-balanced subset, so chance is 50% and a
...               per-item assertion would be noise.  ${DEFECT_HF_MIN_ACCURACY}
...               sets the pass bar — the comparison is STRICT (>), so the
...               default 0.5 means the model must actually beat coin-flipping
...               (a constant YES/NO classifier scores exactly 0.5 on the
...               balanced sample and fails).  The aggregate accuracy is also
...               persisted as RFC_DATA:score for the DB/harness listeners.
...               ${DEFECT_HF_LIMIT} caps how many items run
...               (default 10 to keep CI runtime bounded); override with
...               --variable DEFECT_HF_LIMIT:50 for the full committed subset.
...               The committed list is interleaved vulnerable/safe, so any
...               EVEN prefix stays class-balanced — odd limits are rounded
...               down (a one-class-heavy sample would skew the 50% chance
...               baseline), and limits below 2 are rejected.

Resource          code_review.resource
Library           Collections
Variables         ${CURDIR}/variables/defect_detection_hf.yaml

Default Tags      code_review    defect_detection_hf    benchmark    tier:1    verify:python
Test Tags         axis:model

*** Variables ***
${DEFECT_HF_LIMIT}           10
${DEFECT_HF_MIN_ACCURACY}    0.5

*** Test Cases ***
Defect Detection HF Benchmark Subset
    [Documentation]    Accuracy over the committed Devign subset must beat chance.
    [Timeout]    180 minutes
    ${count}=    Get Length    ${CODE_REVIEW_DEFECT_HF}
    # Round down to an even prefix: the committed list alternates
    # vulnerable/safe, so an odd slice would be one-class-heavy and skew
    # the 50% chance baseline the strict threshold assumes.
    ${end}=    Evaluate    min(int($DEFECT_HF_LIMIT), $count) // 2 * 2
    Should Be True    ${end} >= 2
    ...    DEFECT_HF_LIMIT must be at least 2 to keep the sample class-balanced (got ${DEFECT_HF_LIMIT})
    ${items}=    Get Slice From List    ${CODE_REVIEW_DEFECT_HF}    0    ${end}
    ${results}=    Create List
    FOR    ${item}    IN    @{items}
        ${result}=    CodeReview.Classify Defect In Code    ${item}[func]    ${item}[vulnerable]
        Log    Item ${item}[id] (${item}[project]): expected=${result}[expected] verdict=${result}[verdict] correct=${result}[correct]
        Append To List    ${results}    ${result}[correct]
    END
    ${accuracy}=    CodeReview.Record Defect Detection Accuracy    ${results}
    Log    Defect-detection accuracy: ${accuracy} over ${end} items    console=True
    Should Be True    ${accuracy} > ${DEFECT_HF_MIN_ACCURACY}
    ...    Defect-detection accuracy ${accuracy} not above ${DEFECT_HF_MIN_ACCURACY} over ${end} items
