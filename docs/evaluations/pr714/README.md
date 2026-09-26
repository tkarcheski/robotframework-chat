# PR 714: hardware work on a consumer workstation

**The 1M probe is finished; practical 1M use is not established.** Qwen3.6
completed two answers in 3 h 23 min, both strict failures, including one wrong
physical-resource decision. Qwen3.8 reached the six-hour deadline without a
completed answer. These results justify stopping expansion beyond 1M.

The Make workflow preserves standard Robot reports, actual responses, grades
and database archives. The complete profile at `0182cf7` produced 102 verified
trials per model under one execution-source hash. The framework gate is
**blocked**, with complete evidence and 24 blocking coordinates.

| Current Make profile: strict passes | Qwen3.6 | Qwen3.8 |
|---|---:|---:|
| Short tasks, 4K allocation | 36 / 54 | 36 / 54 |
| Browser tasks, 16K allocation | 0 / 12 | 3 / 12 |
| Context tasks, 16K allocation | 3 / 36 | 24 / 36 |
| Total | 39 / 102 | 63 / 102 |

All 72 context rows have correct factual fields. Exact citations account for
their strict-pass difference. Across the whole profile, mean case fact accuracy
is 87.25% versus 88.24%; a higher aggregate pass count does not remove failed
browser workflows, candidate critical failures or individual regressions.
[Framework gate](make-profile-gate.json) and
[descriptive counts](make-profile-summary.json) preserve that distinction.
Historical results below retain their original instrument identities.

Measured 2026-09-25–26 on one RTX 4090 (24 GiB), Ryzen 7 5800X, 125 GiB RAM.
Both models used Hugging Face Unsloth UD-Q4_K_M weights and Unsloth-native
llama.cpp build 10798, commit d6b1d279f. Initial short-run settings: one slot, full GPU weight offload, f16 KV,
512/128 batches, eight CPU threads, temperature zero, seeds 0/1/2, reasoning off,
no draft model/projector, no automatic fit and no context shifting. No Ollama
inference was used. The two quantized artifacts have different architectures and
mixed-precision recipes; these measurements do not isolate architecture alone.

## Original short tasks at 4K allocation

All 18 cases completed three trials on each model; all **108 result rows** have
verified local/server token accounting. The three greedy repetitions generally
repeat the same outcome and are not independent statistical samples.

| Measure | Qwen3.6-35B-A3B | Qwen3.8-27B |
|---|---:|---:|
| Full passes | 36 / 54 | 36 / 54 |
| Mean case fact accuracy | 98.15% | 94.44% |
| Mean exact evidence-set accuracy | 87.50% | 87.96% |
| Median of per-case mean task latency | 2.50 s | 7.78 s |
| Model load time | 5.02 s | 3.28 s |
| Sampled peak total GPU memory | 22,483 MiB | 16,985 MiB |

Memory includes the desktop and is sampled once per second; it is not an exact
model-only peak. Task latency includes tokenization/setup and model output of varying length;
it is not TTFT or a fixed-token decode-speed comparison. Both models were tested on the same
host serially, Qwen3.8 first, without flushing the OS page cache.

Qwen3.8's fact-score delta was -3.70 percentage points, case-cluster bootstrap
95% interval [-9.26, 0.00]. Neither model demonstrates a large general quality
improvement on this short set. Qwen3.6 was faster on every short task. Incorrect
numeric answer fields remain failures even when the later explanation corrects
them; this happened in the LED calculation. Several otherwise correct answers
failed the strict exact evidence-set rubric. Do not interpret that as a factual
engineering error. Per-case values and uncertainty are in
[short-4k-summary.json](short-4k-summary.json).

## Initial context exploration: 4K, 8K and 16K

Three original cases × four evidence positions × one trial, on each model, at each allocation. The 4K and 8K results were identical:

| Measure | Qwen3.6-35B-A3B | Qwen3.8-27B |
|---|---:|---:|
| Full passes | 2 / 12 | 8 / 12 |
| Mean fact accuracy | 100% | 100% |
| Mean exact evidence-set accuracy | 22.92% | 83.33% |

All 72 rows across the three allocations completed with verified token counts. At 16K, fact accuracy remained 100% on both models. Qwen3.6 citation accuracy fell to 8.33% (1/12 full passes); Qwen3.8 remained at 83.33% (8/12). The difference is **exact citation-identifier and evidence-set compliance**,
not factual-answer accuracy. The citation delta
at 16K is +75.00 points, with a [50.00, 100.00] case-cluster bootstrap interval.
At 4K/8K it is +60.42 points, with a [31.25, 75.00] interval. There
are only **three independent task clusters**. This exploratory result is narrow;
it does not establish general model superiority or full-profile eligibility.
Details: [4K](context-4k-summary.json), [8K](context-8k-summary.json), and [16K](context-16k-summary.json).

Context figures are total allocations with output/wrapper reserve. The initial
4K, 8K and 16K runs used respectively 1708–1763, 5792–5847 and 14018–14070
actual input tokens on both tokenizers. They are not full-length input figures.
Larger-context and product/browser results follow below. These first runs are
historical measurements, not the current-source profile.

## 32K and 64K exploration

Three original cases, spread evidence, one trial per model and allocation, full
GPU weights and f16 KV. All 12 rows completed with verified tokens; both models
retained 100% fact accuracy at both levels. Full passes were 0/3 for Qwen3.6 and
2/3 for Qwen3.8 at each level. Exact-citation accuracy was 0% versus 83.33%.
[32K details](context-32k-summary.json), [64K details](context-64k-summary.json).
The exact-citation distinction persists, but identifier formatting explains much
of it; three cases do not establish general model superiority. The separate 16K bridge also completed.

## 128K capacity and cache comparison

Both models completed three spread-evidence cases at 131,072 allocated tokens
with Q4 KV cache and full GPU weights. All six rows have verified input/output
accounting and 100% factual accuracy. Actual inputs were approximately 128.7K
tokens. Full passes remain 0/3 for Qwen3.6 and 2/3 for Qwen3.8; strict citation
formatting remains a major limitation of that distinction.
[Paired Q4 results](context-128k-q4-summary.json).

The preceding Q8-cache attempt completed all three cases on Qwen3.8, but
Qwen3.6 ran out of VRAM while allocating a 301.28 MiB compute buffer, before any
scored inference. That failure is retained separately from the successful Q4
retry. Both arms used the same cache setting within each experiment; changing
cache precision is a runtime factor, not a model-quality improvement.
[Capacity, token counts and sampled memory](context-128k-capacity.json).

## 262K with managed memory

Both models completed the matched 128K managed-memory bridge, then three cases
each at 262,144 allocated tokens. All six 262K rows are token-verified, with actual inputs of 259,772–259,827
tokens. Qwen3.8 retained 100% factual accuracy; Qwen3.6 averaged 91.67%. In the
final gateware resource case, Qwen3.6 incorrectly reported that simultaneous
operation was feasible. The other two cases remained factually correct. The
8.33-point difference has a case-cluster interval of [0, 25] points over only
three tasks, so it does not establish a broad quality improvement. Strict full
passes remain 0/3 for Qwen3.6 and 2/3 for Qwen3.8.
[Paired 262K results](context-262k-managed-summary.json).

This experiment explicitly enabled process-scoped CUDA managed allocation with
Q4 KV cache. Managed buffers may migrate between GPU and host memory; full GPU
layer offload is not a claim that every page stayed resident in VRAM. Qwen3.6
reached the GPU's physical capacity, while available RAM remained above the
24 GiB reserve. A read-only observation during that arm showed zram use and no
disk-swap use; no system memory settings were changed by this evaluation.
[The consolidated capacity ladder](context-capacity-ladder.json) includes actual
token ranges, runtime factors, memory samples, and both failed startup attempts.
The failed first managed pilot was a runner verification error before inference,
not a model-quality failure. Both the 524K and 1M probes are now terminal.

## 524K with managed memory and YaRN

Both models completed two cases at 524,288 allocated tokens, using Q4 KV,
process-scoped managed memory, YaRN scale 2, spread evidence and one trial.
Actual local inputs were 521,905–521,961 tokens; native prompt accounting was
521,917–521,973 tokens. All four rows were token-verified by the frozen
`0190d50` instrument. They lack newer completion/build metadata and do not
satisfy the current full-profile gate.

| Measure | Qwen3.6-35B-A3B | Qwen3.8-27B |
|---|---:|---:|
| Fact accuracy | 100% | 100% |
| Mean exact evidence-set accuracy | 0% | 75% |
| Full passes | 0 / 2 | 1 / 2 |
| Pin-mux task time | 1,098.85 s | 2,839.45 s |
| Gateware task time | 1,036.41 s | 5,078.81 s |

Task times include setup and different output lengths; background activity was
not isolated. These are descriptive observations, not a dedicated-device speed
benchmark. [Per-case answers, checks, tokens and provenance](context-524k-managed-summary.json)
preserve the official scores and a separately labeled prefix diagnostic.

Qwen3.6 correctly rejected simultaneous use of three SYZYGY transceivers and
M.2 here. Its 262K error did not reproduce on this larger prompt; no monotonic
context-size effect is established. Gateware was selected for this follow-up
after observing that earlier error, so this is not a blind holdout.

Every Qwen3.6 citation carried an extra `DOCUMENT` prefix. Stripping it for known
IDs yields 66.67% on pin-mux and 100% on gateware (83.33% mean) in a post-hoc
diagnostic: its image-name answer also cites an extra pin-mux document.
Qwen3.8 included extra `gateware-requirements` citations for its APB/AXI answers,
leaving its gateware citation score at 50%. Neither difference is a factual
engineering error, and official scores remain unchanged. Two public tasks do
not establish general model superiority.

## Terminal 1M probe

Both arms used Q4 KV, CUDA managed memory, YaRN scale 4 and a 1,000,192-token
native allocation for the 1,000,000-token test budget. Qwen3.6's actual inputs
were 997,636–997,691 tokens. These are small public tasks embedded in synthetic
archive records, not a million tokens of authentic product documentation.

| Observed result | Qwen3.6-35B-A3B | Qwen3.8-27B |
|---|---:|---:|
| Completed answers | 2 / 2 | 0 / 2 |
| Strict passes among completed answers | 0 / 2 | Not scored |
| Mean case fact accuracy | 87.5% | Not scored |
| Exact citation accuracy | 0% | Not scored |
| Cell elapsed time | 12,189 s | 21,605 s; deadline reached |

Qwen3.6's pin-mux facts were all correct; its evidence IDs had the extra
`DOCUMENT` prefix. Its gateware answer incorrectly approved simultaneous use
of three SYZYGY transceivers with M.2, arguing that a requirement overrode the
documented resource limit and inventing an unspecified multiplexing solution.
The other three gateware fields were correct. This is six correct fields out
of seven, distinct from the 87.5% mean across the two case scores.

Qwen3.8 did not finish its first answer before the six-hour bound; its second
case did not run. This is a failed capacity/latency attempt under these settings,
not a measured zero accuracy or proof that every configuration must fail.

[Terminal responses and recorded checks](context-1m-terminal.json) retain the
frozen `0190d50` instrument identity. The missing newer provenance is not filled
in after the fact. The [capacity ladder](context-capacity-ladder.json) preserves
earlier failures and runtime changes. A 24 GiB GPU plus 125 GiB usable RAM is a
consumer workstation; this experiment does not measure minimum RAM or establish
equivalent behavior on a laptop. No beyond-1M run is justified by these results.

## What the citation gap actually measures

Inspecting the responses exposed an important limitation: Qwen3.6 often cites
`DOCUMENT fire-pinmux` rather than the required ID `fire-pinmux`. The strict
rubric rejects that prefix even when the model names the correct document.
A **post-hoc diagnostic**, stripping that one prefix only when it reveals a known
document ID, changes Qwen3.6's mean citation score on the three-case bridge from
0% to 100% at 16K, 88.89% at 32K, and 77.78% at 64K. Qwen3.8 stays at 83.33%.
[Diagnostic details](citation-prefix-diagnostic.json).

Those are not replacement gate scores: no official row or rubric was rewritten.
They show that the large raw citation gap mainly measures identifier serialization
and exact evidence-set compliance, rather than a large difference in finding
engineering evidence. Do not present that gap as a general reasoning improvement.
Context tests remain useful for verified capacity even when both models answer
the engineering questions correctly.

## Historical mixed-revision profile

The historical artifacts cover all **102 required coordinates per model**
(54 short, 12 browser, 36 repeated 16K context). Qwen3.6 passed 39/102 rows;
Qwen3.8 passed 63/102. However, short tasks used one harness revision and the
browser/context tasks used another. A pairwise-only validator originally
reported a blocked gate with 24 regression coordinates
([historical result](historical-mixed-profile-gate.json)).

The strengthened gate requires one harness, fixture and grader revision across
an entire arm, and correctly classifies this combined profile as **incomplete**
([current audit](full-profile-gate.json)). The individual paired experiments
retain their historical scores and recorded provenance. All 102 rows per arm
also predate the explicit `sampling.json_schema` field, so the latest validator
cannot verify their constraint mode. Their serving manifests also lack the now-required
explicit managed-memory boolean when disabled, and their per-call usage predates
the recorded finish reason now required by the shared verifier. They also lack
the newly recorded serving executable/library hashes, retain the older grader,
and store browser traces separately instead of in the result rows. Text rows also
predate parsed-answer archival now required for independent regrading. Calls do not
embed the raw responses now required for answer/action binding, although the
original response files remain in the local artifacts. No missing metadata
is backfilled. Neither
their concatenation nor those legacy artifacts alone satisfy the current gate.
The completed Make profile at the top of this report replaces this historical
profile for current comparison evidence. Historical responses and scores remain
preserved; no row is relabeled with a newer harness hash.

The repeated context arm used 4096 output tokens: both models retained 100% fact
accuracy, while mean exact-citation accuracy was 14.58% for Qwen3.6 and 83.33% for
Qwen3.8. Full passes were 3/36 versus 24/36. The citation delta's case-cluster
interval is [31.25, 100.00] percentage points across only three task clusters.
[Repeated-context details](context-16k-three-trial-summary.json). This remains a
narrow citation-format/evidence-set finding. Each paired coordinate has matching settings;
short and browser/context suites use their separately reported output budgets.

## Model-driven browser tasks at 16K allocation

All four tasks ran three trials per model with a 4096-token output budget. All
24 rows completed with verified token accounting. Qwen3.8 passed 3/12 trials
(the supply-budget task); Qwen3.6 passed 0/12. Qwen3.6 invented non-allowlisted
document selectors in three tasks and returned an answer before completing the
saved-state workflow in the fourth. Qwen3.8's failed tasks ended with malformed
action JSON. No external upload or host write occurred.

The paired pass-rate delta is +25 percentage points, with a case-cluster bootstrap
interval of [0, 75] points over only four task clusters. This does **not** establish
a statistically reliable general improvement. [Per-case results](browser-16k-summary.json).

These historical runs exposed raw dispatcher errors to the model; nine of the
24 traces contain 12 such errors. The updated protocol exposes only fixed
tool-specific failure codes and keeps exception details in private diagnostic
files. Those historical traces are preserved as measured and cannot establish
eligibility under the new replay rules. The completed Make profile uses the
updated protocol and passes its provenance/replay checks; the gate remains
blocked on measured outcomes.

The successful Qwen3.8 trace includes actual document reads, typing into the
report editor, saving, and verification of the saved state:

![Qwen3.8 saved the supply-budget report in the local browser sandbox](browser-qwen38-saved.png)

## Product pilot at 16K allocation

The fresh pilot reserved 4096 output tokens and ran all four product cases three
times per model. Qwen3.8 produced 12/12 token-verified rows and 3/12 strict passes.
Qwen3.6 produced 6/12 token-verified rows and 0/12 strict passes: battery and
telemetry responses reached the output limit. The paired gate correctly returns
**incomplete**, so these counts are not an eligible model comparison or a
superiority claim. [Per-case status](product-16k-output4k-status.json).

Qwen3.8's other nine failures contain prose outside the requested JSON. Native
`json_object` mode was requested but did not enforce object-only output in this
installed Qwen template path. A separate per-request nonempty JSON-schema pilot verified object-constrained
generation, but Qwen3.8 still hit the 4096-token cap on the battery case while
revising inside its explanation. The controller stopped before the second arm;
this failed pilot is not evidence of improved model quality. Larger-context
tests retain the original `json_object` request setting, which did not enforce
object-only output on this installed Qwen path. A review fix makes future
unconstrained runs omit `response_format` entirely; the completed Make profile
used that corrected request configuration. The frozen larger-context runs and
historical metadata are not relabeled. The original responses and strict failures remain preserved; extracting
a fenced JSON block after seeing a failure is diagnostic only, never gate evidence.

The numeric and exact-citation rubric also has limits: for example, the battery
runtime tolerance is 0.000001 hours, so a rounded 46.2857-hour answer misses the
rubric despite being practically equivalent. Such failures should not be described
as wrong release decisions. These public tasks need independently reviewed
precision and evidence-equivalence rules before broad engineering-quality claims.

A response audit separates formatting from arithmetic. In all three sensor
trials, Qwen3.6's machine-readable fields reported 0.0008056640625 A/LSB, 3.3 A
full scale, and 0.1008056640625 A error. Its later explanation calculated the
correct values, but did not repair those fields. Qwen3.8's single fenced object
reported approximately 0.002014 A/LSB, 8.25 A and 0.122014 A; those meet the
numeric tolerances, although preceding prose makes the official response invalid.
Both models returned `release: false`. This is a concrete answer-consistency and
integration difference, not evidence of different release decisions or general
model superiority.

The [post-hoc format diagnostic](product-format-diagnostic.json) retains all
four cases, all three trials, response hashes, and missing extracts from truncated
outputs. It does not replace the strict scores or make the incomplete product
comparison eligible. Qwen3.8's extracted battery runtime also illustrates the
precision limitation above; no numeric value was repaired.

## Test value and follow-up

The original short PWM and board-identity lookups were full passes for both
models in all three trials and add little discrimination here. They are marked
`skip:low-value`; original results and historical gate coverage are preserved.
Safety, abstention, negative and injection controls remain active. Four new
product tasks combine revision handling, numerical budgets, timing losses and
qualification constraints. Their answers were computed independently before
live runs; all successes and failures will be reported.

## Deployment roadmap and model choice

The practical demonstration is an engineering review assistant: assemble source
evidence, compute a budget, identify a conflicting revision, and draft a saved
review. The existing browser demo performs real browser actions; the product
tasks use fictional documents. Neither operates a physical board, parses a
schematic image, qualifies a supplier, or authorizes a production release.

| Stage | Deliverable through robotframework-chat | Exit condition |
|---|---|---|
| Reproducible demo | Make smoke, short tasks, product decisions and saved browser report with raw responses | Completed cases with verified tokens and preserved Robot/database evidence; publish failures too |
| Engineer-assisted pilot | Selected real project documents, explicit revision IDs, calculator-backed numeric checks, draft report | Engineer-approved expected answers and tolerances, held-out projects, measured latency/memory budget |
| Controlled workflow | Read-only retrieval, validated structured output, bounded tools, human sign-off | No critical regression on the agreed profile; exercise outages, injection, abstention and tool failures |
| Model or adapter change | Same Make profile against pinned baseline and candidate | Comparable provenance plus no regression; training data excludes evaluation tasks and traces |

The first stage has demonstrated individual successful workflows; it has not
met an all-tasks-pass threshold. Later stages are proposed work, not delivered
features. In particular, the current model suite grades arithmetic after the
answer; it does not provide the model a deterministic calculator. That is a
useful next intervention because both models sometimes contradict their own
correct calculation in the structured answer fields.

Start an assisted pilot with short, relevant source packets and an explicit
response-time budget. This is a recommendation from the measured failures and
task times, not a measured retrieval-versus-1M comparison. Keep larger-context
probes separate until they show useful answers within the project's budget.
The present 1M result supports neither interactive use nor unattended approval.

No broad model winner is established. Qwen3.6 was faster on the original short
set; Qwen3.8 showed better exact citation compliance and one successful browser
workflow. These differences justify a workload-specific choice, not replacing
one model everywhere. First test harder product decisions and the peer's
isolated prompt experiment. A smaller Qwen is a sensible future cost/latency
arm only after the intended RAM/latency budget and acceptance tasks are fixed;
another download or context sweep alone would not answer a new product question.

The same manifest/Make path accepts other GGUF models supported by the installed
backend. Other providers can use the framework's normal provider configuration,
but this gate requires immutable model/build identity and local token evidence.
Do not label an arbitrary reachable hosted model as a verified comparable arm.
The pinned [Qwen3.6](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/blob/a483e9e6cbd595906af30beda3187c2663a1118c/README.md)
and [Qwen3.8](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/blob/4ca720788d1e01f1bff70c033e0d0028fd02e502/README.md)
cards identify the source artifacts; their advertised capabilities are not
substitutes for the local measured results.

## Assumptions corrected in this review

- **Log preservation:** the native runner now invokes standard Make targets,
  uses distinct run IDs, and emits raw answers/metrics/grades to the listeners.
  Earlier direct-run artifacts remain preserved as historical evidence.
  The Rebot merger now propagates report-generation errors instead of printing
  success after a parse failure; failed model tests still produce usable reports.
- **Context claims:** configured allocation, actual input, completed answers,
  correctness and latency are reported separately. YaRN and managed memory are
  explicit experimental factors. A 125 GiB-RAM host is not a laptop benchmark.
- **Score meaning:** exact ID/set failures, invalid JSON, numerical error and
  unsafe engineering decisions are distinct findings. No post-hoc repair changes
  an official result. The overly strict battery precision remains a documented
  rubric limitation pending independently reviewed replacement criteria.
- **Evidence integrity:** current gates reconstruct prompts, responses and
  browser state and require one compatible harness across an arm. Older rows
  are not backfilled or promoted into the new profile.
- **Documentation:** the local guide now uses Make, current artifact paths and
  one description of the workflow. Stale running/queued 1M claims are replaced
  with terminal evidence. This is a focused PR audit, not certification of every
  AI-generated module in the repository.

## Pinned weights and evidence

- Qwen3.6 repository: `unsloth/Qwen3.6-35B-A3B-GGUF`, revision
  `a483e9e6cbd595906af30beda3187c2663a1118c`, UD-Q4_K_M SHA256
  `ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61`.
- Qwen3.8 repository: `unsloth/Qwen3.8-27B-GGUF`, revision
  `4ca720788d1e01f1bff70c033e0d0028fd02e502`, UD-Q4_K_M SHA256
  `322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482`.
- Shared reference tokenizer: Unsloth Qwen3.8-27B revision
  `3ea932cee0a432ae86e9c7826cbe8aef52323a28`. Each model also uses its own pinned
  tokenizer for input verification; their SHA256 values are in each row.
- Raw local evidence, relative to the evaluation worktree:
  `results/pr714/short-4k-native/` and `results/pr714/context-initial/`.
  Each contains prompts, responses, Robot reports, exact launch/served-context
  manifests, server logs and telemetry. These large local artifacts are not
  committed; the linked JSON reports are compact published summaries.

Reproduce with [the local runner guide](../../hardware-local-eval.md). The
short-run evaluation modules were unchanged across arms (the fixes in 1ed694f).
