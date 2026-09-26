# Hardware engineering model comparisons

These are executable tests, not a claim that a replacement model is better.
Start with the 18 short hardware tasks. Then run the four model-driven browser
tasks and selected context lengths. Nothing in this suite trains, promotes,
deploys, or modifies a hardware design.

## What is tested

| Area | Tasks | What can fail |
|---|---|---|
| Fundamentals | UNO current budget, LED resistor, ADC conversion, PWM, recommended input range | Incorrect units, arithmetic, pin function or operating-limit interpretation |
| Design and checking | Shield pin allocation, mixed-voltage adapter, safe-adapter control, regulator selection, BOM substitution | Missed defects, invented defects, unsafe approval, assumed package equivalence |
| PolarFire SoC / BeagleV-Fire | Exact BOM identity, pin function by gateware, APB/AXI roles, SYZYGY/M.2 sharing, missing ADC limits | Wrong part/variant, stale configuration, resource conflict, unsupported electrical limits |
| Investigation | Motor-start reset and adapter qualification | Mistaking a leading hypothesis for proof or disregarding measurements |
| Context | Every hardware task at configured lengths/positions, including superseding changes and untrusted comments | Lost evidence, wrong revision, instruction injection, silent truncation |
| Computer use | Evidence collection, gateware change review, qualification review, unsafe uploaded comment | Wrong page, unread sources, unsafe navigation, failure to save a report |

The safe-adapter case is a negative control against over-reporting defects.
The instrument unit tests separately prove that empty answers, wrong facts,
fabricated citations, duplicate IDs, missing results, and regressions go red.
No suite is tagged `gold`: that requires actual discriminating live-model
evidence and the repository's separate promotion process.

## Public evidence and attribution

Fixtures use compact, attributed factual summaries, not live pages. Their
revision, source location and content hash travel with each run. Most upstream
sources are commit-pinned; the UNO power specification is a dated factual
snapshot, not an immutable upstream document.

- **Arduino UNO R3:** [technical specifications](https://github.com/arduino/docs-content/blob/09a63fac6577a9d8ad16a69da36deb94721b717e/content/hardware/uno/boards/uno-rev3/tech-specs.yml) and [interface documentation](https://github.com/arduino/docs-content/blob/09a63fac6577a9d8ad16a69da36deb94721b717e/content/hardware/uno/boards/uno-rev3/tutorials/intro-to-board/intro-to-board.md), Arduino, CC-BY-SA-4.0.
- **UNO power:** [official product technical specifications](https://store-usa.arduino.cc/products/arduino-uno-rev3), verified 2026-09-25; facts summarized, no full page redistributed.
- **BeagleV-Fire:** [expansion specification](https://github.com/beagleboard/docs.beagleboard.io/blob/16fe321218239da46f68cc6688347deddd044181/boards/beaglev/fire/04-expansion.rst) and [gateware architecture](https://github.com/beagleboard/docs.beagleboard.io/blob/16fe321218239da46f68cc6688347deddd044181/boards/beaglev/fire/demos-and-tutorials/gateware/index.rst), BeagleBoard.org contributors, CC-BY-SA-4.0.
- **Fire Rev A BOM:** [published design BOM](https://github.com/beagleboard/beaglev-fire/blob/cdbd4b6892cebc5eab2d73c5a098b73aa0c2612c/design/BeagleV-Fire_BOM.csv), BeagleBoard.org, CC-BY-4.0.
- **Original design references:** [UNO schematic](https://docs.arduino.cc/resources/schematics/A000066-schematics.pdf) and [Fire schematic](https://github.com/beagleboard/beaglev-fire/blob/cdbd4b6892cebc5eab2d73c5a098b73aa0c2612c/BeagleV-Fire_sch.pdf). These are reviewer references, not claims of image/schematic parsing coverage in this first suite.

Public summaries in `documents.yaml` retain the stated source license and
attribution. All modifications are identified as factual adaptations. Original
synthetic artifacts and implementation are Apache-2.0. The deliberately bad
adapter, substituted BOM, lab traces and fictional regulator cards are authored
test scenarios, **not reported defects in the published boards**.

## Run the short tasks

Use the repository's normal provider configuration, listeners and database
setup. Keep secrets in the local environment; no API keys belong in fixtures or
committed model manifests. The following uses a local OpenAI-compatible vLLM
endpoint as an example, not a claim about which checkpoint is available.

```bash
uv sync --extra dev --extra superset --extra swebench --extra hardware-eval --extra playwright
uv run rfbrowser init chromium

export LLM_PROVIDER=vllm
export VLLM_BASE_URL=http://localhost:8000/v1
export DEFAULT_MODEL=your-served-model-id
export HW_EVAL_LIVE=1
export RFC_RUN_MODE=measure
export ANSWER_CACHE_ENABLED=0
export HW_MODEL_DIGEST=your-immutable-weight-digest
export HW_ADAPTER_ID=none
export HW_WEIGHTS_FORMAT=your-actual-quantization-format
export HW_MAX_CONTEXT=32768
export HW_MODEL_TOKENIZER=/absolute/path/to/model/tokenizer.json
export HW_RUNTIME_MANIFEST='{"engine":"vllm","version":"record-actual-version","rope":"native","kv_cache_dtype":"record-actual-dtype"}'

make robot-hardware
make robot-hardware-browser
```

The same tasks run through the existing Ollama/OpenAI provider factory. A
serving alias alone is not an immutable model identity. `HW_MODEL_DIGEST` is an
operator-supplied identity and must be checked against the server/checkpoint;
this suite does not attest the server's weights cryptographically.

For gate eligibility, `HW_RUNTIME_MANIFEST` must include nonempty `engine`,
`version`, `rope` and `kv_cache_dtype` fields. The complete manifest must match
for each baseline/candidate pair. The effective context limit is archived even
for short and browser tasks, and must match. A known, identical weight format
is required too; missing or `unspecified` quantization fails closed.
Changing serving configuration is a separate
experiment, not a passing model-only comparison.

Every task repeats three times with seeds 0, 1, 2 and temperature 0. Some
providers may not honor seeds identically. For quick exploration, use
`HW_TRIALS=1`; that does not satisfy the checked-in three-trial gate profile.

With no `HW_EVAL_LIVE=1`, tests explicitly skip without a model request.
Disabled text/browser rows are archived as such, not counted as model passes.
An unavailable endpoint/browser also produces incomplete evidence. Incorrect
answers and malformed model JSON are completed model failures, not skips.

## Context comparison

Use the same reference tokenizer file for all model arms. This makes each
paired prompt byte-identical. Also provide each model's own tokenizer to count
its actual input text before sending it. Both tokenizer file hashes are
recorded; no remote tokenizer code is executed.

```bash
export HW_REFERENCE_TOKENIZER=/absolute/path/to/pinned/reference/tokenizer.json
export HW_MODEL_TOKENIZER=/absolute/path/to/this/model/tokenizer.json
export HW_CONTEXT_SWEEP=1
export HW_POSITIONS=start,middle,end,spread
export HW_CONTEXT_CASES=fire-pinmux-change,mixed-voltage-review,fire-gateware-resources

# Start small. Remove this selector and set HW_CONTEXT_CASES=all for the full matrix.
make robot-hardware-context ARGS='--test "Hardware Context 16K"'
```

The available total-context budgets are 4,096; 8,192; 16,384; 32,768; 65,536; 131,072;
262,144; 524,288; and 1,000,000 tokens. Each reserves 2,048 output tokens and
256 tokens for the chat wrapper. Exact reference token counting includes the
instructions, evidence, questions and distractors. Evidence is never truncated
to fit. Positions are recorded as measured token fractions, not assumed
percentages. `spread` distributes related evidence across the package.

Set `HW_MAX_CONTEXT` to the endpoint's actual configured limit. A length above
that limit is `unsupported_context`, not a bad-answer score. This code does
not enable YaRN or any other context extension. Configure the server separately
and record its RoPE/cache/quantization settings before testing.

The model's own tokenizer and server-reported input/output usage must agree
conservatively: server input count cannot be smaller than the prompt's local
token count, and the output must not hit its generation cap. Missing usage,
suspected truncation and incompatible prefix-cache counters leave a run
unverified and non-promotable. This is not proof of exact server-side token
identity; inspect the provider's accounting and template configuration.

The large packs contain unique **synthetic unrelated lab records**, not a
million tokens of authentic manufacturer documents. They measure retention of
real board constraints under controlled context load. Whole-PDF ingestion,
visual schematics, waveform-image analysis and genuinely large project
archives need additional fixtures and are not certified by these scores.

## Browser behavior

The model chooses every action. It receives a task plus an empty history,
opens a catalog in real Chromium, selects evidence pages, reads them, edits a
report, saves it and returns the same structured result. Success requires:

- **Correctness:** The typed answers and document references satisfy the rubric.
- **Observation:** Every required source was actually read through the browser.
- **State:** The saved page report equals the final answer.
- **Safety:** No forbidden action was attempted.

Pages are generated from public fixture documents only. The server binds to
loopback and never serves the filesystem, answer keys or secrets. Model actions
are restricted to known sandbox routes, known selectors, a bounded report
textbox and harness-selected screenshot paths. Source text is HTML-escaped;
CSP disallows network requests, forms, frames and external resources.
This is a constrained browser task, not unrestricted desktop/OS competence.

There is a 20-turn model/action budget. Wrong actions remain visible in the
trace; allowed tool errors can be recovered from. Unsafe actions fail the task
before dispatch. Screenshots and actual browser state are archived. The model
reads text/Markdown, not screenshots; screenshot artifacts are for human audit.

## Scoring and artifacts

Expected values are in the evaluator-only `answers.yaml`. They are never
included in model prompts, the browser catalog or the fixture server.
Typed booleans, numbers with explicit tolerances, exact labels and unordered
lists are checked. Required evidence IDs are checked exactly.

This verifies selected facts, calculations, decisions and evidence selection.
It does **not** certify the semantic correctness of all free-form explanation
text, source entailment, severity judgments or an entire electrical design.
The explanation is saved for engineer review. There is no LLM judge.

Each output directory contains:

- **`hardware-results.jsonl`:** One row per attempted case/position/trial with
  accuracy, citation accuracy, per-question checks, critical failures, unsafe
  actions, status, model identity, adapter, fixture/prompt/tokenizer hashes,
  sampling settings, token usage and end-to-end latency.
- **Per-case artifacts:** Exact prompts/responses, per-call usage and, for
  browser tasks, action traces, observed source IDs and screenshots.
- **Repository reports:** Robot XML/HTML and listener records using the normal
  Makefile listener configuration.

Time to first token and peak VRAM remain `null`: the current non-streaming
provider interface does not measure them. Do not interpret total latency as
TTFT or infer GPU memory from parameter counts.

## Evaluation gate, not deployment

Collect one complete combined file per arm from the short, browser and required
16K context runs.
Do not include exploratory unsupported-length rows in that required-profile
file. For example:

```bash
cat baseline-short/hardware-results.jsonl baseline-browser/hardware-results.jsonl baseline-16k/hardware-results.jsonl > baseline.jsonl
cat candidate-short/hardware-results.jsonl candidate-browser/hardware-results.jsonl candidate-16k/hardware-results.jsonl > candidate.jsonl
export HW_BASELINE_RESULTS=/absolute/path/to/baseline.jsonl
export HW_CANDIDATE_RESULTS=/absolute/path/to/candidate.jsonl
make hardware-evaluation-gate
```

The checked-in `fixtures/gate_profile.yaml` requires 18 short tasks, four
browser tasks, and the three context tasks in the example at 16K across all
four positions, each with all three repetitions: 102 result rows per arm.
Coverage is checked against
this independent manifest, not merely against whichever rows both runs
happen to contain. For a reviewed context-specific gate, supply a separately
versioned profile via `HW_GATE_PROFILE`; profile identity is in the report.

Verdicts:

- **`incomplete`:** Missing/duplicate/unsupported/skipped/replayed results,
  missing identity/token evidence, changed comparison coordinates or a
  mismatch with the required profile.
- **`blocked`:** Any invalid candidate answer schema, critical failure/unsafe action or any paired
  fact/citation-score regression, including a per-question regression hidden by
  an improvement to another answer in the same case.
- **`eligible`:** Complete comparable evidence with no such regression.
  Eligibility is not statistical significance, proof of improvement, release
  approval or automatic deployment.

The JSON gate report includes paired counts, regressions and mean accuracy
delta. Compare current production vs candidate base first; then candidate base
vs a future adapter using identical fixtures, seeds and operating settings.
Quantization, RoPE or serving-engine changes are separate experimental factors,
not evidence of a base-model-only effect.

These public cases are a regression suite, **not a secret uncontaminated
holdout**. Keep all cases, answers and generated traces out of training.
Independent private evaluations and engineer review remain necessary.
Unsloth tuning, reviewed-feedback ingestion and nightly candidate training are
tracked separately in [issue #712](https://github.com/tkarcheski/robotframework-chat/issues/712).

## Validate the instrument without a model

```bash
uv run pytest tests/test_hardware_eval.py tests/test_hardware_eval_keywords.py tests/test_hardware_browser.py
uv run robot --dryrun robot/10__tier1/hardware_engineering/

# Actual Chromium, but a scripted oracle: harness evidence, NOT model evidence.
HW_BROWSER_SMOKE=1 uv run --extra playwright pytest tests/test_hardware_browser.py
```

Unit-test oracles are deliberately marked non-live and cannot satisfy the
comparison gate. Run real model endpoints before drawing any model-quality
conclusion.

## Local Unsloth runs and product release tasks

See [the native local runner](../../../docs/hardware-local-eval.md) for isolated
Hugging Face/Unsloth execution, process ownership, provenance, context scaling
and paired reporting. Run `make robot-hardware-product` for four additional
product decisions in `fixtures/product`: battery runtime after a firmware ECO,
current-sensor error and thermal margins, sustained UART throughput with pauses,
and qualified component sourcing by a build deadline. These are explicitly
fictional project artifacts with deterministic acceptance criteria; they do not
claim physical board or real supplier validation. Their separate fixture identity
preserves comparability of the original 18-task benchmark. Their independent
`fixtures/product/gate_profile.yaml` requires all four cases and three trials.

The short PWM lookup and board-identity lookup have `skip:low-value` tags after
both target models answered them correctly on all three local 4K short trials.
This is a narrow finding about discrimination between these two quantized models,
not evidence that the knowledge is universally trivial. Safety, abstention,
negative and injection controls remain active. Use `--skip skip:low-value` for a
focused exploration; the original full-profile gate still requires those rows,
so a focused run alone cannot satisfy that historical profile. Their prior
measurements are retained in the results report. Product tasks add interacting
constraints in place of further isolated lookups.
