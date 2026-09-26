# Local hardware model evaluation

Use **Make → Robot Framework → the standard listeners** for inference and
comparison. `make hardware-local-eval` manages one native llama.cpp server at a
time with pinned Hugging Face GGUF weights. Its child runs use the normal
`robot-hardware*` targets and database archive. Coordinate GPU ownership first.

This uses Unsloth's installed llama.cpp build. It does not run Ollama inference
or change Studio's resident model. The adapter is named `vllm` because it speaks
the compatible chat API; the actual engine is recorded separately.

## Prepare once

Use the repository database configuration and install the evaluation extras:

```bash
uv sync --extra dev --extra superset --extra hardware-eval --extra playwright
make .env
export PLAYWRIGHT_BROWSERS_PATH="$PWD/results/browser-cache"
uv run rfbrowser init chromium
uv run --env-file .env rfc harness start --tool codex --no-version-probe
```

Use your agent's harness tool name. An active session links agent/test metrics;
it does not establish a completed run. Freeze execution source and dependencies
across comparison arms. Create a private manifest with one entry per model:

```json
[
  {
    "name": "baseline",
    "id": "unsloth/Qwen3.6-35B-A3B-GGUF",
    "path": "/absolute/path/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    "sha256": "actual SHA256 of the weight file",
    "revision": "pinned Hugging Face revision",
    "quant": "UD-Q4_K_M",
    "tokenizer": "/absolute/path/model-tokenizer.json",
    "native_context": 262144
  }
]
```

Execution validates weight hashes and tokenizer files before starting a server.
Keep weights immutable. Use one pinned reference tokenizer across arms; each
model also has its own tokenizer for input verification. The installed Unsloth
binary may need its `build/bin` and NVIDIA runtime directories in
`LD_LIBRARY_PATH`. Keep private manifests, weights and outputs under `results/`.

## One completed case before a sweep

Omit `--execute` to print a plan without loading a model. Then run one live case
and inspect its response, grade, Robot report and listener archive:

```bash
make hardware-local-eval ARGS='--models results/models.json --server /absolute/path/to/llama-server --reference-tokenizer /absolute/path/reference-tokenizer.json --contexts 4096 --suites context --cases fire-pinmux-change --positions spread --trials 1 --timeout 180 --cell-timeout 600 --output results/hardware-smoke --execute'
```

Each invocation needs a fresh output directory. Wrong answers are preserved
model failures. Outages, truncated outputs, missing token evidence and partial
coverage cannot establish model quality. Examine failures before expanding.

## Comparison profile

The main profile requires 102 rows per model: 54 short, 12 browser and 36 context.
Use the same manifest, source and dependencies for both stages:

```bash
make hardware-local-eval ARGS='--models results/models.json --server /absolute/path/to/llama-server --reference-tokenizer /absolute/path/reference-tokenizer.json --contexts 4096 --suites short --trials 3 --output-tokens 2048 --output results/hardware-short --execute'

make hardware-local-eval ARGS='--models results/models.json --server /absolute/path/to/llama-server --reference-tokenizer /absolute/path/reference-tokenizer.json --contexts 16384 --suites browser context --trials 3 --output-tokens 4096 --positions start,middle,end,spread --output results/hardware-browser-context --execute'
```

For the separate product corpus use `--suites product` at 16K, three trials and
a fresh directory. Its four tasks cover battery runtime after a firmware change,
current-sensor error/thermal margins, UART capacity and qualified parts sourcing.
These are fictional engineering artifacts, not connected-board measurements or
real supplier qualification.

## Preserved evidence and the gate

Read `suites.<suite>.robot_output_dir` in the controller manifest; Robot files no
longer live beneath each controller cell:

```bash
jq '.status, .suites' results/hardware-short/baseline-4096/manifest.json
```

Robot outputs use `results/<version>/<model>/<suite>/<host>/<run-id>/`. Each
suite receives a unique `RUN_ID`; `SESSION_ID` links the active harness session.
For repeated direct Make calls in one active session, supply a fresh `RUN_ID`
yourself; the native runner does this automatically for each child suite.
Outputs include XML/HTML reports, `hardware-results.jsonl`, prompts/responses,
and browser screenshots/traces. Standard listener fields contain actual answers,
metrics and grades. Verify the database listener's archive confirmation rather
than treating local files as proof of database preservation.

The manifest records `make_exit`. A nonzero inner Make result can represent
scored model failures; controller completion is not an all-tests-pass claim.
Running snapshots are not completed cases. Cooperative interruption preserves
terminal evidence; abrupt kills may leave only partial files. Keep failures,
timeouts and interrupted runs.

Concatenate the three actual Robot files per arm, then run the public gate.
Replace these example paths with the manifest's `robot_output_dir` values:

```bash
cat baseline-short/hardware-results.jsonl baseline-browser/hardware-results.jsonl baseline-context/hardware-results.jsonl > results/baseline.jsonl
cat candidate-short/hardware-results.jsonl candidate-browser/hardware-results.jsonl candidate-context/hardware-results.jsonl > results/candidate.jsonl
make hardware-evaluation-gate \
  RUN_ID=baseline-vs-candidate-v1 \
  HW_BASELINE_RESULTS="$PWD/results/baseline.jsonl" \
  HW_CANDIDATE_RESULTS="$PWD/results/candidate.jsonl" \
  HW_REFERENCE_TOKENIZER=/absolute/path/reference-tokenizer.json
```

For products also set
`HW_GATE_FIXTURES="$PWD/robot/10__tier1/hardware_engineering/fixtures/product"`.
That profile requires four cases and three trials per arm. Do not mix exploratory
lengths, product rows or changed harness revisions into the main profile.

The gate checks independent coverage, trusted fixtures, reparsed responses,
recomputed grades, prompt reconstruction, token usage and runtime/model identity.
It retokenizes long text with the pinned reference tokenizer and replays browser
read/save evidence. Matching self-declared pass flags are insufficient. Artifact
consistency is not cryptographic attestation of a remote server. See
[gate meanings and scoring limits](../robot/10__tier1/hardware_engineering/README.md#evaluation-gate-not-deployment).

## Context and memory experiments

`--contexts` is total allocation including the output reserve and a 256-token
wrapper reserve. Native allocation rounds upward to 256-token blocks: a
1,000,000-token test allocates 1,000,192 tokens. Report actual input counts too.
The pack places a small engineering task among deterministic archive distractors;
it is not a million tokens of authentic product documentation.

Defaults: full GPU weight offload, f16 KV, one slot, 512/128 batches, eight CPU
threads, thinking off, no speculative/vision model, host prompt cache, automatic
fit or context shifting. Above native context the runner adds integer-scale
YaRN. This is experimental extension, not proof of answer quality.

`--kv`, `--gpu-layers`, `--kv-placement`, `--cpu-ffn-layers`, `--cpu-moe-layers`
and `--unified-memory` change runtime factors. Use matched arms and a smaller
bridge when changing them. Process-scoped CUDA managed memory may move pages
between VRAM and RAM; full offload does not establish full VRAM residency.
CPU-only mode disables GPU placement and cannot combine with managed memory.
Sampled reserve checks are not hard memory limits. Failures stop the owned
processes and preserve telemetry/logs; system memory settings are unchanged.

An output cap or non-normal completion remains unverified. `--constrain-json`
is a separately recorded object-schema experiment: it constrains syntax, not
arithmetic or evidence. Otherwise requests omit `response_format`. Do not repair
answers after generation and present them as original passes.

## Interpretation and other models

Report facts, exact citation sets, strict passes and latency separately. Repeated
greedy trials are not independent samples. Three public context cases cannot
establish general model superiority. Citation serialization failures can coexist
with correct facts. Total task latency is not TTFT; sampled machine GPU memory
is not a model-only peak.

The [PR714 evidence and deployment roadmap](evaluations/pr714/README.md)
cover a 24 GiB RTX 4090 workstation with 125 GiB usable RAM, not a typical laptop
or a measured minimum-RAM requirement. Other models can use the same manifest
when the installed native backend supports them; verify compatibility and fit.
For other supported API providers use the
[normal Robot provider workflow](../robot/10__tier1/hardware_engineering/README.md#run-the-short-tasks).
Endpoint reachability alone does not supply the immutable identity, local token
counts and serving provenance required by this comparison gate.
