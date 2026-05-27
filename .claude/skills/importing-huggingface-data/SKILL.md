---
name: importing-huggingface-data
description: >-
  Imports external LLM-evaluation benchmarks/datasets from Hugging Face (GSM8K,
  MMLU, TruthfulQA, ARC, HellaSwag, HumanEval) as test inputs for the
  robotframework-chat framework. Covers the static-import approach (download once,
  convert to YAML, commit) versus the dynamic-import approach (load at runtime),
  authentication, licensing/contamination considerations, and suite registration.
when_to_use: >-
  Trigger when the user wants to add a Hugging Face dataset or benchmark as test
  data, test a model against GSM8K/MMLU/etc., or asks how to bring external
  evaluation data into the rfc test suites.
---

# Importing Hugging Face test data

Use this skill to import external LLM-evaluation benchmarks from Hugging Face as
test inputs, so local models can be tested against established benchmarks.

> The full conversion script, keyword library, Python tests, and Robot test
> examples live in [`reference.md`](reference.md). This file is the overview and
> decision guide.

## Relevant datasets

| Dataset | HF ID | Maps to Suite | Tier |
|---------|-------|---------------|------|
| GSM8K | `openai/gsm8k` | `robot/math/` | 0–2 (deterministic answers) |
| MMLU | `cais/mmlu` | New suite | 2+ (multiple choice, needs grading) |
| MMLU-Pro | `TIGER-Lab/MMLU-Pro` | New suite | 2+ (harder, 10 options) |
| TruthfulQA | `truthful_qa` | New suite | 2–3 (factual accuracy) |
| ARC | `allenai/ai2_arc` | New suite | 2+ (science reasoning) |
| HellaSwag | `Rowan/hellaswag` | New suite | 2+ (commonsense) |
| HumanEval | `openai/openai_humaneval` | `robot/docker/python/` | 4 (code exec) |

## Authentication

The `datasets` library picks up `HF_TOKEN` from the environment. Set it in
`.env` (see `.env.example`). A **Read** token is optional for public datasets
(avoids rate limits) and required for gated datasets. Create one at
https://huggingface.co/settings/tokens.

## Which approach?

- **Static import (recommended for deterministic tests).** Best for tier:0/tier:1
  where answers are known and fixed (e.g. GSM8K math). Download once, convert to
  YAML, and commit a small subset to the repo. See `reference.md` §
  "Approach A".
- **Dynamic import (for exploratory / tier:6 runs).** Load the full dataset at
  runtime without committing it; requires the `datasets` library at run time. See
  `reference.md` § "Approach B".

## Data considerations

- **License check.** Verify each dataset's license on its HF page before
  importing (GSM8K/MMLU/HellaSwag/HumanEval are MIT; TruthfulQA Apache-2.0; ARC
  CC-BY-SA with attribution).
- **Size.** Don't commit full datasets — use `--limit` to take a 50–100 item
  subset. Version the import *script*, not the raw data.
- **Contamination.** Many models were trained on these benchmarks, so high
  scores may reflect memorization. Prefer harder variants (GSM1K, MMLU-Pro), add
  perturbations, or compare across benchmarks to spot outliers.

## Registration

New suites built from HF data must be registered in **both**
`config/test_suites.yaml` and `config/local_models.yaml` (exact YAML in
`reference.md` § "Registration"). Then verify with `make robot-dryrun`.
