# Self-Healing LLM Test Framework: Design Document

> **Status:** Design (not yet implemented)
> **Branch:** `feat-self-healing-deco`
> **Author:** tkarcheski
> **Date:** 2026-04-25
> **Patent:** Provisional filing planned. Core IP in private submodule.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Solution Overview](#2-solution-overview)
3. [Part I: Self-Healing Listener + Decorator](#3-part-i-self-healing-listener--decorator)
4. [Part II: LoRA Fine-Tuning Pipeline](#4-part-ii-lora-fine-tuning-pipeline)
5. [IP Separation Strategy](#5-ip-separation-strategy)
6. [Integration with Existing Codebase](#6-integration-with-existing-codebase)
7. [Hardware & Infrastructure](#7-hardware--infrastructure)
8. [Database Schema Additions](#8-database-schema-additions)
9. [Configuration](#9-configuration)
10. [Verification Plan](#10-verification-plan)
11. [Open Questions](#11-open-questions)

---

## 1. Problem Statement

LLM test failures in robotframework-chat are currently **static**. When a test
fails, the result is logged to the database and archived, but the system does
not adapt. Prompts are not improved, parameters are not tuned, and models are
not fine-tuned based on accumulated evidence.

The existing retry mechanism (`Ask And Grade With Retry` in
`src/rfc/keywords.py:122`) scales `max_tokens` by 8x on failure, but this is
a single-axis strategy limited to token budget issues. It does not modify
prompts, switch models, adjust temperature/seed, or learn from historical
failures.

**Goal:** Build a closed-loop system where test failures drive automatic
improvement at three levels:

1. **Immediate** (during test execution) -- self-healing retries with prompt
   modification, parameter tuning, and model fallback.
2. **Nightly** (batch job) -- an analyzer agent reviews accumulated failures
   and produces training datasets.
3. **Periodic** (fine-tuning) -- LoRA adapters trained on failure data are
   deployed back into the testing pipeline.

---

## 2. Solution Overview

```
                        RUNTIME (Part I)
                        ================
Robot Test Execution
  |
  +-- @self_healing decorator (opt-in per keyword)
  |     +-- Intercepts failures from Grader.grade()
  |     +-- Applies strategy chain:
  |     |     1. Prompt modification (LLM rewrites prompt)
  |     |     2. Parameter adjustment (temperature, top_p, seed, max_tokens)
  |     |     3. Model fallback (try different model/endpoint)
  |     |     4. Escalate (create GitHub issue)
  |     +-- Emits RFC_DATA for every attempt
  |
  +-- SelfHealingListener (standalone, opt-in)
        +-- Captures all keyword failures + healing metadata
        +-- Writes to database (new schema columns)
        +-- Feeds nightly analyzer

                        BATCH (Part II)
                        ===============
Nightly Analyzer Agent (fresh session, cron-triggered)
  |
  +-- 1. Query DB for recent failures (full context)
  +-- 2. Build training dataset (failures + synthetic augmentation)
  +-- 3. LLM reviews dataset quality
  +-- 4. LoRA fine-tune (grader, tested model, test-fixer)
  +-- 5. Evaluate fine-tuned model vs. base
  +-- 6. Deploy to Ollama if evaluation passes
  +-- 7. Create GitHub issue if evaluation fails
```

---

## 3. Part I: Self-Healing Listener + Decorator

### 3.1 Architecture

Two components, each opt-in:

| Component | Type | Activation | Purpose |
|-----------|------|------------|---------|
| `@self_healing` | Python decorator | Applied to keyword methods | Wraps keyword execution with retry + strategy chain |
| `SelfHealingListener` | Robot Listener v3 | Added to `--listener` arg | Captures healing events across all tests, writes to DB |

The decorator handles **active healing** (modify and retry). The listener
handles **passive observation** (record what happened for the nightly batch).
Both are required when the LLM is "listening" (learning from failures).

#### Decorator invocation styles

The decorator supports two equivalent forms:

```python
# Structured config — explicit knobs.
@self_healing(config=SelfHealingConfig(fallback_models=["qwen2.5:32b"]))

# Prose form — natural language with @skill-name tokens.
@self_healing("@timeout-skill retry with longer timeout, adjust other variables")
@self_healing("@modify-skill retry with agent-x's suggestions")
```

Prose directives are parsed into two parts: ``@skill-name`` tokens that select
preset config overrides (see ``SKILL_CONFIG_OVERRIDES`` in
``src/rfc/self_healing.py``), and the remaining prose, which becomes
**guidance** handed to the LLM during prompt rewriting. The two forms can be
combined — skill overrides layer on top of an explicit ``config``.

Initial registered skills:

| Skill | Effect on `SelfHealingConfig` |
|-------|-------------------------------|
| `@timeout-skill` | `max_prompt_retries=0`, `max_param_retries=5` — bias toward parameter/timeout retries. |
| `@modify-skill`  | `max_prompt_retries=4`, `max_param_retries=0` — bias toward LLM-driven prompt rewrites. |

Unknown skill tokens are ignored with a warning so adding new skills is
backwards-compatible.

### 3.2 Strategy Chain

Strategies are applied in escalation order. Each strategy is attempted before
moving to the next. The chain stops on the first successful grade.

```
Strategy 1: PROMPT MODIFICATION
  - Send the failed prompt + expected answer + actual answer + failure reason
    to an LLM (can be the same model, fresh context).
  - The LLM rewrites the prompt with clarifications, examples, or constraints.
  - Retry with the modified prompt.

Strategy 2: PARAMETER ADJUSTMENT
  - Modify inference parameters:
    - Temperature: try 0.0 (deterministic), then 0.3, then 0.7
    - max_tokens: 8x scaling (existing behavior from Ask And Grade With Retry)
    - seed: try 3 different seeds
    - top_p / top_k: adjust if model supports it
  - Each combination is a separate attempt.

Strategy 3: MODEL FALLBACK
  - Try a different model from the configured fallback list.
  - E.g., if phi4:14b fails, try qwen2.5:32b.
  - Fallback models are configured per test suite in test_suites.yaml.

Strategy 4: ESCALATE
  - Create a GitHub issue with:
    - Test name, suite, tier
    - All attempted strategies and their results
    - Full prompt history (original + all modifications)
    - Model, parameters, and failure context
  - Uses `gh issue create` via subprocess.
```

### 3.3 Decorator Design

The `@self_healing` decorator composes with Robot Framework's `@keyword()`
decorator. It wraps the keyword method, intercepts failures (low grade scores
or exceptions), and applies the strategy chain.

```python
# src/rfc/self_healing.py

from functools import wraps
from typing import Callable, List, Optional
from dataclasses import dataclass
from .rfc_data import emit_rfc_data
from .models import GradeResult


@dataclass
class HealingAttempt:
    """Record of a single self-healing attempt."""
    attempt_number: int
    strategy: str           # "prompt", "params", "model", "escalate"
    prompt_used: str
    parameters: dict        # temperature, max_tokens, seed, etc.
    model_used: str
    result: Optional[GradeResult]
    success: bool


class SelfHealingConfig:
    """Configuration for the self-healing decorator."""
    max_prompt_retries: int = 2
    max_param_retries: int = 3
    fallback_models: List[str] = []
    escalate_to_github: bool = True
    github_repo: str = "tkarcheski/robotframework-chat"
    score_threshold: float = 1.0   # minimum passing score


def self_healing(
    config: Optional[SelfHealingConfig] = None,
) -> Callable:
    """Decorator that adds self-healing retry to a grading keyword.

    Composes with @keyword() -- apply @self_healing() ABOVE @keyword():

        @self_healing(config=SelfHealingConfig(fallback_models=["qwen2.5:32b"]))
        @keyword("My Graded Keyword")
        def my_keyword(self, prompt, expected):
            ...
    """
    cfg = config or SelfHealingConfig()

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            attempts: List[HealingAttempt] = []

            # --- Try original execution ---
            result = _try_execution(fn, self, args, kwargs, attempts, 0)
            if _is_passing(result, cfg.score_threshold):
                _emit_healing_data(attempts, success=True)
                return result

            # --- Strategy 1: Prompt modification ---
            for i in range(cfg.max_prompt_retries):
                modified_prompt = _rewrite_prompt(self, args, kwargs, attempts)
                new_args = _replace_prompt(args, modified_prompt)
                result = _try_execution(fn, self, new_args, kwargs, attempts, len(attempts))
                if _is_passing(result, cfg.score_threshold):
                    _emit_healing_data(attempts, success=True)
                    return result

            # --- Strategy 2: Parameter adjustment ---
            for params in _param_variations(self, cfg.max_param_retries):
                _apply_params(self, params)
                result = _try_execution(fn, self, args, kwargs, attempts, len(attempts))
                if _is_passing(result, cfg.score_threshold):
                    _emit_healing_data(attempts, success=True)
                    return result

            # --- Strategy 3: Model fallback ---
            original_model = self.client.model
            for model in cfg.fallback_models:
                self.client.model = model
                result = _try_execution(fn, self, args, kwargs, attempts, len(attempts))
                if _is_passing(result, cfg.score_threshold):
                    self.client.model = original_model
                    _emit_healing_data(attempts, success=True)
                    return result
            self.client.model = original_model

            # --- Strategy 4: Escalate ---
            if cfg.escalate_to_github:
                _create_github_issue(cfg, attempts)

            _emit_healing_data(attempts, success=False)
            return result  # return last failed result

        return wrapper
    return decorator
```

### 3.4 Listener Design

The `SelfHealingListener` extends `BaseListener` (from
`src/rfc/base_listener.py`) to capture healing metadata emitted via RFC_DATA.

```python
# src/rfc/self_healing_listener.py

from typing import Any, ClassVar, Dict
from .base_listener import BaseListener


class SelfHealingListener(BaseListener):
    """Captures self-healing events for database persistence and nightly analysis.

    Opt-in: add to --listener when self-healing is active.
    Requires: SelfHealingConfig to be set on the keyword library.
    """

    ROBOT_LISTENER_API_VERSION = 3

    TRACKED_KEYWORDS: ClassVar[Dict[str, str]] = {
        "Ask LLM": "input",
        "Grade Answer": "grading",
        "Ask And Grade With Retry": "grading",
    }

    def __init__(self) -> None:
        super().__init__()
        self._healing_events: list = []

    def on_test_end(self, data: Any, result: Any) -> None:
        """Capture healing metadata from RFC_DATA at test end."""
        healing_data = {
            k: v for k, v in self._current_test_data.items()
            if k.startswith("self_healing_")
        }
        if healing_data:
            self._healing_events.append({
                "test_name": data.name,
                "test_status": result.status,
                "healing": healing_data,
            })

    def on_suite_end(self, data: Any, result: Any) -> None:
        """Write all healing events to database at suite end."""
        if self._healing_events:
            self._persist_healing_events()

    def _persist_healing_events(self) -> None:
        """Write healing events to the test database."""
        # Implementation: use TestDatabase to write to
        # self_healing columns in test_result_artifacts
        ...
```

### 3.5 New RFC_DATA Keys

These keys are emitted by the `@self_healing` decorator and captured by
`SelfHealingListener`:

| Key | Type | Description |
|-----|------|-------------|
| `self_healing_attempts` | int | Total number of healing attempts |
| `self_healing_strategy` | str | Final strategy that succeeded (or "exhausted") |
| `self_healing_strategies_tried` | JSON | Array of all strategies attempted |
| `self_healing_prompt_history` | JSON | Array of all prompt versions used |
| `self_healing_success` | bool | Whether any healing attempt succeeded |
| `self_healing_original_error` | str | The failure reason that triggered healing |
| `self_healing_duration_seconds` | float | Total time spent on healing attempts |

### 3.6 Analyzer Agent

A fresh-session LLM agent that reviews test failures. It is **not** part of
the test execution -- it runs as a separate process (nightly cron or manual
trigger).

```python
# src/rfc/analyzer_agent.py

class AnalyzerAgent:
    """Reviews test failures and recommends improvements.

    Runs as a fresh LLM session (not during test execution).
    Can be the same model but MUST be a fresh context.

    Escalation order:
    1. Suggest prompt improvements
    2. Suggest test input changes
    3. Suggest model parameter changes
    4. Create GitHub issue requesting human help
    """

    def analyze_failures(self, failures: list) -> list:
        """Analyze a batch of test failures.

        Args:
            failures: List of dicts with keys:
                - test_name, test_suite, model_name
                - question, expected_answer, actual_answer
                - grading_reason, score
                - self_healing_strategies_tried (if any)

        Returns:
            List of recommendations, each with:
                - recommendation_type: "prompt" | "input" | "params" | "escalate"
                - details: specific changes to make
                - confidence: 0.0-1.0
        """
        ...

    def create_training_pairs(self, failures: list) -> list:
        """Convert failures into training data pairs for fine-tuning.

        Each pair: {"prompt": ..., "completion": ..., "metadata": ...}
        """
        ...
```

---

## 4. Part II: LoRA Fine-Tuning Pipeline

### 4.1 Architecture

```
scripts/nightly_finetune.py (cron entry point)
  |
  +-- src/rfc/fine_tuning/pipeline.py
        |
        +-- dataset_builder.py
        |     +-- Query DB for failures (test_result_artifacts)
        |     +-- Filter: score < threshold
        |     +-- Extract: question, expected, actual, grading_reason
        |     +-- Augment: LLM generates synthetic hard cases
        |     +-- Review: LLM validates dataset quality
        |     +-- Output: data/training/{model}/{date}/train.jsonl
        |
        +-- lora_trainer.py
        |     +-- Load base model
        |     +-- Apply LoRA config (rank, alpha, target modules)
        |     +-- Train on dataset
        |     +-- Save LoRA delta only (not merged model)
        |     +-- Output: data/adapters/{model}-ft{N}/adapter_model.safetensors
        |
        +-- evaluator.py
        |     +-- Load base model + LoRA adapter
        |     +-- Run evaluation suite (subset of test suites)
        |     +-- Compare scores: fine-tuned vs. base
        |     +-- Largest LLM sets timeout pace
        |     +-- Output: evaluation report
        |
        +-- model_registry.py
              +-- Track: base model -> adapter mappings
              +-- Version: {model}-ft{N} auto-increment
              +-- Store in: config/model_registry.yaml
              +-- Git-backed: commit adapter metadata
```

### 4.2 Training Data Pipeline

**Source:** `test_result_artifacts` table in PostgreSQL.

```
test_result_artifacts
  |
  +-- SELECT question, expected_answer, actual_answer, grading_reason,
  |          thinking_text
  |   FROM test_result_artifacts tra
  |   JOIN test_results tr ON tra.result_id = tr.id
  |   WHERE tr.score < 0.5       -- failed tests only
  |     AND tr.tag_tier >= 2     -- LLM-graded tests
  |     AND tr.test_status = 'FAIL'
  |
  +-- For each failure:
  |     1. LLM creates training pair:
  |        - input: original question
  |        - output: correct answer (from expected_answer or LLM-generated)
  |        - metadata: model, suite, tier, failure reason
  |     2. LLM generates 2-3 synthetic variations (harder cases)
  |     3. LLM reviews all pairs for quality (reject low-confidence)
  |
  +-- Output format (JSONL):
        {"messages": [
          {"role": "system", "content": "..."},
          {"role": "user", "content": "..."},
          {"role": "assistant", "content": "..."}
        ], "metadata": {"source": "failure", "model": "...", "suite": "..."}}
```

### 4.3 LoRA Training

**Framework:** Unsloth or PEFT (TBD based on model compatibility with Ollama).

**LoRA configuration (defaults):**

```yaml
# config/fine_tuning.yaml
lora:
  rank: 16
  alpha: 32
  dropout: 0.05
  target_modules: ["q_proj", "v_proj", "k_proj", "o_proj"]
  learning_rate: 2e-4
  epochs: 3
  batch_size: 4
  gradient_accumulation_steps: 4
  warmup_ratio: 0.1
  max_seq_length: 2048
```

**Training targets (three models in pipeline):**

| Model | Purpose | Training Data |
|-------|---------|---------------|
| Grader model | Improve grading accuracy | Failed grades where human/consensus disagrees |
| Tested model | Improve the model being tested | Failed test prompts + correct completions |
| Test-fixer model | Specialized failure analyst | Failure context + recommended fixes |

### 4.4 LoRA Checkpoint Management

- **Store LoRA deltas only** -- never merge into base model permanently.
- **Rebuild on demand** using Ollama Modelfile:

```dockerfile
# data/adapters/qwen2.5-32b-ft1/Modelfile
FROM qwen2.5:32b
ADAPTER ./adapter_model.safetensors
PARAMETER temperature 0.0
PARAMETER num_ctx 4096
```

```bash
ollama create qwen2.5:32b-ft1 -f data/adapters/qwen2.5-32b-ft1/Modelfile
```

- **Version scheme:** `{base_model}-ft{N}` where N auto-increments.
- **Registry:** `config/model_registry.yaml` tracks all versions.

### 4.5 Evaluation

Before deploying a fine-tuned model, it must pass evaluation:

1. Select a representative subset of test suites (math, safety, coding).
2. Run the same tests against both base model and fine-tuned model.
3. Compare aggregate scores. Fine-tuned model must score >= base on all suites.
4. The **largest LLM** (e.g., qwen2.5:32b) sets the pace for timeouts --
   all evaluations use this model's timing as the baseline.
5. If evaluation passes: auto-deploy via `ollama create`.
6. If evaluation fails: create GitHub issue with comparison report.

### 4.6 Deployment

Automatic replacement in Ollama after successful evaluation:

```bash
# 1. Create fine-tuned model in Ollama
ollama create {model}-ft{N} -f data/adapters/{model}-ft{N}/Modelfile

# 2. Update config/model_registry.yaml
# 3. Update config/test_suites.yaml to use fine-tuned model (optional)
# 4. Previous version remains available as {model}-ft{N-1}
```

---

## 5. IP Separation Strategy

The system is split between public and private repositories to enable patent
filing while maintaining an open-source testing framework.

### Public Repository (this repo, MIT/Apache-2.0)

- Abstract base classes and protocols (interfaces)
- "Naive" implementations:
  - Simple token-scaling retry (already exists in `Ask And Grade With Retry`)
  - Basic dataset extraction from database
  - Standard LoRA training wrapper
- Configuration schemas (YAML format definitions)
- Documentation of the general concept
- All Robot Framework tests and listeners

### Private Submodule (separate git repo)

- **Adaptive strategy selection algorithm** -- the logic that decides which
  healing strategy to apply based on failure patterns, model characteristics,
  and historical success rates.
- **Synthetic data generation prompts** -- the specific prompts used to
  generate hard cases and augment training data.
- **Fine-tuning hyperparameter optimization** -- the algorithm that adapts
  LoRA configuration based on model size, failure type, and training history.
- **Evaluation scoring rubrics** -- the weighted scoring system for
  comparing fine-tuned vs. base models.
- **Patent-specific novelty claims** -- documentation of the novel aspects
  for provisional patent filing.

### Integration

```
robotframework-chat/               # Public repo
  +-- src/rfc/self_healing.py       # Public interfaces + naive impl
  +-- src/rfc/fine_tuning/          # Public pipeline scaffolding
  +-- private/                      # git submodule (private repo)
        +-- adaptive_strategy.py    # Proprietary strategy selection
        +-- synthetic_gen.py        # Proprietary data generation
        +-- hp_optimizer.py         # Proprietary hyperparameter tuning
        +-- eval_rubrics.py         # Proprietary evaluation logic
```

The public code checks for the private submodule at runtime. If present,
it uses the proprietary implementations. If absent, it falls back to the
naive implementations.

---

## 6. Integration with Existing Codebase

### 6.1 Files Modified

| Existing File | Changes |
|---------------|---------|
| `src/rfc/test_database.py` | Add self-healing columns to `test_result_artifacts` |
| `config/test_suites.yaml` | Add `self_healing:` and `fine_tuning:` sections |
| `Makefile` | Add `fine-tune`, `evaluate-ft`, `healing-report` targets |
| `src/rfc/keywords.py` | Apply `@self_healing` decorator to `Ask And Grade With Retry` |
| `src/rfc/__init__.py` | Export new modules |

### 6.2 Files Created

| New File | Purpose |
|----------|---------|
| `src/rfc/self_healing.py` | Decorator + strategy engine + config |
| `src/rfc/self_healing_listener.py` | Robot Listener v3 for healing events |
| `src/rfc/analyzer_agent.py` | Nightly failure analysis agent |
| `src/rfc/fine_tuning/__init__.py` | Package init |
| `src/rfc/fine_tuning/pipeline.py` | Orchestration |
| `src/rfc/fine_tuning/dataset_builder.py` | DB to JSONL |
| `src/rfc/fine_tuning/lora_trainer.py` | LoRA training wrapper |
| `src/rfc/fine_tuning/evaluator.py` | Pre/post comparison |
| `src/rfc/fine_tuning/model_registry.py` | Version tracking |
| `scripts/nightly_finetune.py` | Cron entry point |
| `config/model_registry.yaml` | Base-to-adapter mapping |
| `config/fine_tuning.yaml` | Training hyperparameters |
| `tests/test_self_healing.py` | Unit tests for decorator + listener |
| `tests/test_fine_tuning.py` | Unit tests for pipeline |
| `robot/ci/self_healing_smoke.robot` | Integration smoke test |

### 6.3 Existing Patterns Reused

| Pattern | Source | Reuse |
|---------|--------|-------|
| `BaseListener` template method | `src/rfc/base_listener.py` | `SelfHealingListener` extends it |
| `RFC_DATA` protocol | `src/rfc/rfc_data.py` | All healing metadata uses `emit_rfc_data()` |
| `GradeResult` dataclass | `src/rfc/models.py` | Healing checks `result.score` |
| `retry_on_transient()` | `src/rfc/retry.py` | Healing adds strategy-level retry above transient retry |
| `Grader.grade()` | `src/rfc/grader.py` | Healing wraps grading failures |
| Token scaling retry | `keywords.py:122` (Ask And Grade With Retry) | Strategy 2 subsumes this |
| `create_provider()` | `src/rfc/llm_client.py` | Model fallback creates new provider instances |
| `OllamaClient` | `src/rfc/ollama.py` | Fine-tuned model deployment via Ollama API |

---

## 7. Hardware & Infrastructure

### 7.1 Available Hardware

| Node | Hardware | VRAM/RAM | Role |
|------|----------|----------|------|
| ai1 | P100 GPU + Tenstorrent TPU | 16GB VRAM | Large model training |
| dev1/dev2 | 4090 GPU | 24GB VRAM | Primary training (small/medium) |
| mini2 (this machine) | Mac Mini M4 Pro | 64GB unified | Inference, evaluation, orchestration |
| Mini1 | Mac Mini | varies | Inference node |
| Framework | Framework laptop | varies | Development, small experiments |
| OpenRouter | External API | N/A | Fallback evaluation, large model access |

### 7.2 Hardware Routing

Fine-tuning jobs are routed based on model size:

| Model Size | Target Hardware | Estimated Training Time |
|------------|----------------|------------------------|
| < 8B params | 4090 (24GB) | ~30 min / epoch |
| 8B-16B params | 4090 (24GB) with 4-bit quant | ~1-2 hr / epoch |
| 16B-32B params | P100 (16GB) with 4-bit quant | ~2-4 hr / epoch |
| > 32B params | OpenRouter (no fine-tune) or skip | N/A |

Evaluation (inference only) runs on Mac Minis with 64GB unified memory,
which can load models up to ~32B at full precision.

---

## 8. Database Schema Additions

### 8.1 New Columns on `test_result_artifacts`

```sql
ALTER TABLE test_result_artifacts ADD COLUMN
    self_healing_attempts INTEGER DEFAULT 0;
ALTER TABLE test_result_artifacts ADD COLUMN
    self_healing_strategies TEXT DEFAULT '';    -- JSON array
ALTER TABLE test_result_artifacts ADD COLUMN
    self_healing_final_strategy TEXT DEFAULT '';
ALTER TABLE test_result_artifacts ADD COLUMN
    self_healing_prompt_history TEXT DEFAULT '';  -- JSON array
ALTER TABLE test_result_artifacts ADD COLUMN
    self_healing_duration_seconds FLOAT DEFAULT 0.0;
ALTER TABLE test_result_artifacts ADD COLUMN
    self_healing_success BOOLEAN DEFAULT FALSE;
```

### 8.2 New Table: `fine_tuning_runs`

```sql
CREATE TABLE fine_tuning_runs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    base_model TEXT NOT NULL,
    adapter_name TEXT NOT NULL,          -- e.g., "qwen2.5:32b-ft1"
    training_samples INTEGER NOT NULL,
    epochs INTEGER NOT NULL,
    lora_rank INTEGER NOT NULL,
    lora_alpha INTEGER NOT NULL,
    learning_rate FLOAT NOT NULL,
    training_loss FLOAT,
    eval_score_base FLOAT,              -- base model score on eval suite
    eval_score_finetuned FLOAT,         -- fine-tuned model score
    deployed BOOLEAN DEFAULT FALSE,
    hardware_node TEXT,                  -- which node trained this
    duration_seconds FLOAT,
    dataset_path TEXT,                   -- path to training JSONL
    adapter_path TEXT,                   -- path to LoRA adapter
    git_commit TEXT,                     -- commit SHA of training code
    notes TEXT DEFAULT ''
);

CREATE INDEX idx_ft_runs_model ON fine_tuning_runs(base_model);
CREATE INDEX idx_ft_runs_timestamp ON fine_tuning_runs(timestamp);
```

### 8.3 New Table: `model_versions`

```sql
CREATE TABLE model_versions (
    id SERIAL PRIMARY KEY,
    model_name TEXT NOT NULL UNIQUE,     -- e.g., "qwen2.5:32b-ft1"
    base_model TEXT NOT NULL,            -- e.g., "qwen2.5:32b"
    adapter_path TEXT NOT NULL,
    fine_tuning_run_id INTEGER REFERENCES fine_tuning_runs(id),
    created_at TIMESTAMP NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,     -- currently deployed in Ollama
    eval_score FLOAT,
    notes TEXT DEFAULT ''
);

CREATE INDEX idx_model_versions_base ON model_versions(base_model);
CREATE INDEX idx_model_versions_active ON model_versions(is_active);
```

---

## 9. Configuration

### 9.1 test_suites.yaml Additions

```yaml
self_healing:
  enabled: false                  # opt-in globally
  score_threshold: 1.0            # minimum passing score
  max_prompt_retries: 2           # prompt modification attempts
  max_param_retries: 3            # parameter variation attempts
  escalate_to_github: true
  github_repo: "tkarcheski/robotframework-chat"
  fallback_models:                # ordered fallback list
    - "qwen2.5:32b"
    - "qwen3.5:27b"
  param_variations:
    temperatures: [0.0, 0.3, 0.7]
    seeds: [42, 123, 7]

fine_tuning:
  enabled: false
  schedule: "0 2 * * *"          # 2 AM daily
  min_failures: 10               # minimum failures before training
  score_threshold: 0.5           # failures below this are training candidates
  eval_suites:                   # suites used to evaluate fine-tuned models
    - math
    - safety
    - accounting
  hardware:
    training_node: "dev1"        # default training node
    eval_node: "mini2"           # default evaluation node
```

### 9.2 config/fine_tuning.yaml

```yaml
lora:
  rank: 16
  alpha: 32
  dropout: 0.05
  target_modules: ["q_proj", "v_proj", "k_proj", "o_proj"]
  learning_rate: 2e-4
  epochs: 3
  batch_size: 4
  gradient_accumulation_steps: 4
  warmup_ratio: 0.1
  max_seq_length: 2048

dataset:
  min_samples: 50                # minimum training samples
  max_samples: 5000              # cap to prevent overfitting
  synthetic_ratio: 0.3           # 30% synthetic augmentation
  validation_split: 0.1          # 10% held out for validation
  quality_review: true           # LLM reviews dataset before training

evaluation:
  min_improvement: 0.0           # fine-tuned must be >= base (no regression)
  suites: ["math", "safety", "accounting"]
  timeout_model: null            # auto-detect largest model
  auto_deploy: true              # deploy to Ollama if evaluation passes
```

### 9.3 config/model_registry.yaml

```yaml
# Auto-maintained by fine_tuning/model_registry.py
# Manual edits are overwritten on next fine-tuning run.

models:
  qwen2.5:32b:
    active_adapter: null         # no fine-tuned version yet
    adapters: []

  phi4:14b:
    active_adapter: null
    adapters: []
```

---

## 10. Verification Plan

### 10.1 Unit Tests

```bash
uv run pytest tests/test_self_healing.py    # decorator, strategies, config
uv run pytest tests/test_fine_tuning.py     # pipeline, dataset builder, registry
```

### 10.2 Integration Tests

```bash
# Robot suite that intentionally triggers failures and verifies healing
make robot -s robot/ci/self_healing_smoke.robot

# Dry run to verify listener registration
make robot-dryrun
```

### 10.3 Fine-Tuning Smoke Test

```bash
# Single fine-tune pass on a toy dataset
python scripts/nightly_finetune.py --dry-run

# Verify Ollama loads the adapter
ollama create test-ft1 -f data/adapters/test-ft1/Modelfile
ollama run test-ft1 "Hello, world"
ollama rm test-ft1
```

### 10.4 End-to-End

```bash
# Full pipeline: run tests → collect failures → build dataset → train → evaluate → deploy
python scripts/nightly_finetune.py --full

# Verify deployment
ollama list | grep ft
make robot -s robot/math  # run against fine-tuned model
```

### 10.5 Pre-Commit

```bash
uv run pytest
pre-commit run --all-files
make code-quality-check
make robot-dryrun
```

---

## 11. Open Questions

1. **Analyzer agent endpoint:** Should the nightly analyzer use the same
   Ollama endpoint as tests, or a dedicated one? (Risk: analyzer load
   interferes with overnight test runs.)

2. **Minimum failure threshold:** How many failures before triggering
   fine-tuning? Too few = training on noise. Proposed: 10 failures minimum,
   configurable in `config/fine_tuning.yaml`.

3. **GitHub issue template:** What fields should the escalation issue
   include? Proposed: test name, suite, tier, model, all strategies tried,
   prompt history, full error context.

4. **Superset dashboards:** Should self-healing metrics get a dedicated
   dashboard or integrate into existing dashboards? Proposed: new
   "Self-Healing" dashboard with:
   - Healing success rate over time
   - Most effective strategies per suite
   - Tests that consistently need healing (candidates for prompt rewrite)
   - Fine-tuning impact (before/after scores)

5. **OpenRouter models:** Fine-tuning isn't possible for external API models.
   Should we: (a) skip them entirely, (b) use them only for evaluation, or
   (c) generate training data from their failures but train local models?
   Proposed: (c) -- use their failures as training signal for local models.
