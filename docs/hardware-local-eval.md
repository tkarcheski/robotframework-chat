# Local hardware model evaluation

`scripts/hardware_local_eval.py` runs the PR hardware Robot suites against one
owned native llama.cpp process at a time. It uses local Hugging Face GGUF weights;
it does not start Ollama, change Studio's resident model, download weights, or
change global memory settings. Coordinate exclusive GPU ownership before running.

Create a private JSON manifest (keep model files and outputs under `results/`):

```json
[
  {
    "name": "baseline",
    "id": "unsloth/Qwen3.6-35B-A3B-GGUF",
    "path": "/absolute/path/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    "sha256": "verified SHA256 of this file",
    "revision": "pinned Hugging Face revision",
    "quant": "UD-Q4_K_M",
    "tokenizer": "/absolute/path/baseline-tokenizer.json",
    "native_context": 262144
  }
]
```

Add one entry per arm. Preflight validates all declared fields, positive native
context, weight-file presence, and loadable model/reference tokenizer files
before output creation or server probing. Dry plans validate metadata without
requiring downloaded files. Verify the SHA256 values before executing; the manifest
records operator-supplied identities and is not a cryptographic server attestation.
Pin model/tokenizer revisions and keep the same reference tokenizer across arms.
The requested context is the **total allocation**, including 2,048 output tokens
and 256 wrapper-reserve tokens. Actual prompt counts are in each result row.

Use an isolated project environment with the `hardware-eval` and `playwright`
extras. Initialize Chromium with `rfbrowser init chromium` before browser tasks.
Point `PLAYWRIGHT_BROWSERS_PATH` at a project-local directory during installation
and execution when using a private browser cache.

```bash
# First print the exact server commands. Execution requires --execute.
python scripts/hardware_local_eval.py \
  --models results/models.json \
  --server /absolute/path/to/unsloth/llama.cpp/build/bin/llama-server \
  --reference-tokenizer /absolute/path/reference-tokenizer.json \
  --contexts 4096 --suites short --trials 3 \
  --output results/hardware-short-4k
```

For the installed Unsloth binary, both its `build/bin` directory and the installed
NVIDIA runtime library directory may need to be in `LD_LIBRARY_PATH`. Prefer the
binary beside its backend libraries. The runner verifies an allocation belonging
to its own PID in `nvidia-smi`; a server that silently falls back to CPU does not
produce a GPU benchmark.

The defaults use full weight offload, f16 KV, one slot, 512/128 batches, eight
threads, reasoning off, no speculative draft model, no vision projector, no host
prompt cache, no automatic fit and no context shifting. The model's native
context comes from the manifest. Above that length the command explicitly adds
YaRN with an integer scale covering the allocation. This is an experimental
extension setting, **not proof of quality or support at that length**.

Start the context ladder after examining short-task results:

```bash
python scripts/hardware_local_eval.py \
  --models results/models.json --server /absolute/path/to/llama-server \
  --reference-tokenizer /absolute/path/reference-tokenizer.json \
  --contexts 4096 8192 16384 --suites context --trials 1 \
  --output results/hardware-context-initial --execute
```

The default context subset has three cases and four evidence positions. Increase
trials to three for the checked-in 16K gate profile. Browser history needs a
larger allocation than a short task; test it separately at 16K or above. Continue
32K → 64K → 128K → 262K → 524K → 1M only after checking capacity, token accounting,
answers and resource usage at the preceding step. `--kv`, `--gpu-layers`,
`--kv-placement`, `--cpu-ffn-layers` and `--cpu-moe-layers` expose separate
cache/weight placement factors; changing them requires matched arms and a fresh
output. Requested case/position/trial coverage is checked against an independent
profile before a cell can complete; a nonempty partial result file cannot pass.

Each model/context directory preserves its command, runtime manifest, served
context properties, GPU allocation, model-load time, Robot artifacts, model
prompts/responses, server log, and sampled memory telemetry. The server is stopped
in `finally`; no unrelated process is signalled. Occupied ports, insufficient
initial GPU headroom, RAM reserve violations, process failure, incomplete rows or
unverified token accounting stop expansion. These guards are sampled and do not
provide a hard cgroup memory limit. Inspect the failure before retrying in a new
output directory. Wrong model answers remain completed failures and do not stop
collection of the other cases.

## Comparing results

```bash
python scripts/summarize_hardware_eval.py \
  results/short/baseline-4096/short/hardware-results.jsonl \
  results/short/candidate-4096/short/hardware-results.jsonl \
  --output results/paired-short-summary.json
```

The summary separates fact accuracy, exact evidence-set accuracy, full-case
passes and latency. It rejects unequal coverage, changed paired coordinates and
incomplete/token-unverified runs. It bootstraps **case IDs**, keeping repetitions
and positions together, because repeated greedy trials are not independent
samples. Its practical-improvement indicator requires at least ten percentage
points and a positive lower bound in the case-cluster bootstrap interval. This
small public regression set cannot establish general model superiority; the
summary does not replace the independent full-profile gate.

A case that every model passes is a ceiling-effect candidate. Keep safety,
negative and infrastructure controls unless there is evidence they no longer
serve that purpose. Mark `skip:low-value` only after examining multiple model
arms and context conditions, and state the evidence/replacement. Do not retune
answers, discard failures, or select tasks to force a preferred model to win.

### Input allocation and output budget

`HW_MAX_CONTEXT` is the declared server allocation and is archived as
`effective_context_tokens`. A smaller context sweep coordinate sizes its input
package; it does not resize an OpenAI-compatible server. The runner verifies the
native server allocation before each cell. Transports supporting per-request
context receive that same declared allocation.

`--output-tokens` (default 2048) sets `HW_OUTPUT_TOKENS`, the request limit and
reserved output space; it is recorded in each row's held-fixed sampling metadata.
Use a fresh paired run when changing this limit. An output hitting the limit
remains unverified and stops expansion, even if its partial text looks correct.

The first 16K product pilot reached the 2048-token output limit on six Qwen3.8
responses and stopped before its second model arm or browser tests. It is archived
under `results/pr714/product-browser-16k/` and is not a paired comparison. A fresh
product run uses a 4096-token output budget. Leading prose outside the requested
JSON remains a schema failure; we do not repair model output for the gate.

### Separating JSON formatting from task quality

The native runner also accepts `--constrain-json`, which sends an explicit
`{"type":"object"}` schema in each chat request and records that constraint in
its held-fixed runtime manifest. It constrains syntax, not answer IDs, numerical
values, evidence choices, or browser actions. Treat it as a fresh matched
experiment; do not combine constrained and unconstrained rows in a model pair.
Before scored tasks, a bounded probe asks for plain text and must still return a
complete JSON object. Its raw response is archived even when validation fails;
probe time is recorded separately from model-load and task latency.

The installed build's specialized Qwen template checks for a nonempty schema;
ordinary OpenAI `json_object` mode supplies an empty schema. Live product/browser
responses consequently included prose and XML tool-call markers despite that
request mode. Those remain strict failures in the original runs. An explicit
native constraint can test whether formatting or engineering decisions dominate
the observed difference; it does not repair already generated answers.

The first server-wide grammar probe failed before any scored task: the grammar
could not consume Qwen's chat prefix. The runner therefore uses the compatible
chat API's nonempty `json_schema` response format, allowing the native template
parser to account for that prefix. `HW_JSON_OBJECT_CONSTRAINT=1` enables the same
request-level behavior in the Robot keyword and archives the schema in sampling
metadata. The transport's ordinary JSON mode remains unchanged by default.

Native allocations are explicitly rounded **up** to 256-token blocks, matching
this llama.cpp build. The context-suite coordinate still sizes the input pack.
For example, the 1,000,000-token budget requests a 1,000,192-token server
allocation, verifies that exact served value, and records it as effective context.
No context reduction or eviction is enabled.

### CUDA managed allocation for larger capacity probes

`--unified-memory` explicitly sets `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` only in the
owned child process. The runner checks CUDA managed-memory and concurrent-access
capabilities, records them with the runtime factor, and keeps its available-RAM
reserve checks active. Without this flag it removes an inherited opt-in from the
child, so an ambient setting cannot silently change the experiment. No system VM,
swap, service, or other process configuration is changed.

The installed native backend uses `cudaMallocManaged` on this path; the local
RTX 4090 reports both required capabilities. This permits a separate capacity
experiment where CUDA can migrate pages between device and system memory.
It does not establish usable latency, correct long-context answers, or completed
inference. Run a matched smaller-context bridge before interpreting a larger
managed-memory result. Keep quantization, allocation mode, and CPU placement
explicit when comparing arms.

Dry plans include the command, test budget, rounded allocation, output budget,
JSON-constraint setting and managed-memory setting; they do not launch a server.

The artifact gate validates SHA256 prompt, fixture and harness identities, a
nonempty grader version, boolean question checks, and critical-failure totals
recomputed from those checks. Browser workflow regressions (evidence read or
report saved) block eligibility even if final answer accuracy is unchanged. The
harness identity snapshots every Python module in the local `rfc` package once
per process, including transport, parsing and browser execution code. Complete
paired runs must use one unchanged implementation; do not mix old and new
harness identities in a comparison.

For managed allocations, the runner requires its own CUDA process plus native
GPU layer-offload and CUDA model-buffer evidence. It does not require the usual
1024 MiB per-process VRAM threshold: managed pages can migrate between host and
GPU, so allocation is not proof of residency. See the [CUDA unified-memory
placement documentation](https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/unified-memory.html).
Total GPU/RAM telemetry and completed inference remain separate measurements.
The initial managed pilot stopped at this old residency check before any scored
request; its failure artifacts are retained.

Each token-verified row must identify its model tokenizer by SHA256; the identity
must remain constant within a model arm. Long-context rows also require the
reference-tokenizer hash used to size the input. Different model arms may use
different model tokenizers. Browser question-level critical counts remain the
counts derived from question checks; missing evidence reads or saved reports
block the workflow gate separately. CPU-only launches explicitly record that
GPU allocation verification was not performed.

An entire comparison arm must use one fixture, grader and harness revision, as
well as one model-tokenizer identity. Matching versions only within individual
case pairs is insufficient when combining suites into a promotion profile.
Blank or nonstring model digests cannot establish weight identity.

The owned runner launches base GGUF weights directly and explicitly records
adapter identity `none`, overriding any inherited `HW_ADAPTER_ID`. Its headroom
guard checks every GPU reported by `nvidia-smi` before launch and rejects missing
or nonnumeric memory readings. This is conservative: devices hidden from CUDA
are also checked, so a busy hidden device can prevent a run.
CPU-only runs (`--gpu-layers 0`) skip GPU probes and headroom checks, force
`--device none` and CPU KV placement, and retain RAM/process telemetry. GPU
telemetry is recorded as null. Combining CPU-only mode with CUDA managed
allocation is rejected before launch.

Gate validation loads the trusted benchmark separately from result artifacts.
Every row must match its fixture hash and its case's exact question IDs and
critical flags, including browser cases. Matching omissions in both model arms
cannot establish coverage. The core comparison API requires this benchmark;
the Robot keyword supplies its loaded fixtures. The descriptive summary CLI
uses the main fixtures by default; use `--fixtures PATH` for the product corpus
or an archived fixture revision.

The owned child drops inherited `LLAMA_ARG_*` overrides and `LLAMA_API_KEY`.
This prevents ambient chat templates, draft models, server modes or unrelated
authentication from changing the recorded native launch. Library paths and
CUDA device visibility remain available; the parent environment is unchanged.

The offline Robot gate accepts `HW_GATE_FIXTURES` alongside `HW_GATE_PROFILE`.
For product results, set the fixture root to
`robot/10__tier1/hardware_engineering/fixtures/product`; its `gate_profile.yaml`
is then the default profile. Both paths can be set explicitly for archived runs.
The gate also validates full-pass flags against schema validity, all question
and citation checks, unsafe actions, and (for browser rows) evidence reads and
report saves. A mutually consistent comparison cannot inflate full-pass rates
by trusting an inconsistent `passed` field.

Run manifests archive `source.patch`, the binary-capable diff against HEAD,
including staged and unstaged tracked changes. Its SHA256 and base revision are
recorded; untracked evaluation inputs under `src`, `robot`, `scripts`, `config`,
`pyproject.toml` and `uv.lock` cause a refusal before server launch. Private output
directories are outside that check.

Token verification now also requires an explicit normal completion reason
(`stop`). A provider-declared length stop, filtering stop or missing reason
remains unverified even when its reported output is below the requested limit.
Older artifacts keep their original validator revision and do not receive an
inferred completion-reason flag. Each arm must also retain one weight format
across its entire profile.
