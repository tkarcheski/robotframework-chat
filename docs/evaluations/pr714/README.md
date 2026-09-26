# PR 714 local evaluation — preliminary results

Measured 2026-09-25 on one RTX 4090 (24 GiB), Ryzen 7 5800X, 125 GiB RAM.
Both models used Hugging Face Unsloth UD-Q4_K_M weights and Unsloth-native
llama.cpp build 10798, commit d6b1d279f. One slot, full GPU weight offload, f16 KV,
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
| Median of per-case mean request latency | 2.50 s | 7.78 s |
| Model load time | 5.02 s | 3.28 s |
| Sampled peak total GPU memory | 22,483 MiB | 16,985 MiB |

Memory includes the desktop and is sampled once per second; it is not an exact
model-only peak. Latency includes model output of varying length and is not TTFT
or a fixed-token decode-speed comparison. Both models were tested on the same
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

All 72 rows across the three allocations completed with verified token counts. At 16K, fact accuracy remained 100% on both models. Qwen3.6 citation accuracy fell to 8.33% (1/12 full passes); Qwen3.8 remained at 83.33% (8/12). The difference is **citation
selection under distractors**, not factual-answer accuracy. The citation delta
is +60.42 points, with a [31.25, 75.00] case-cluster bootstrap interval, but there
are only **three independent task clusters**. This exploratory result is narrow;
it does not establish general model superiority or full-profile eligibility.
Details: [4K](context-4k-summary.json), [8K](context-8k-summary.json), and [16K](context-16k-summary.json).

The 4K context figure is a total allocation with output/wrapper reserve, not a
4,096-token input. Exact actual token counts remain in the raw result rows.
Larger contexts, actual model-driven browser tasks and the new product cases are
still being evaluated. No 1M inference claim is made in this checkpoint.

## Test value and follow-up

The original short PWM and board-identity lookups were full passes for both
models in all three trials and add little discrimination here. They are marked
`skip:low-value`; original results and historical gate coverage are preserved.
Safety, abstention, negative and injection controls remain active. Four new
product tasks combine revision handling, numerical budgets, timing losses and
qualification constraints. Their answers were computed independently before
live runs; all successes and failures will be reported.

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
