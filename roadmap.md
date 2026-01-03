# robotframework-chat — Project Roadmap

This roadmap follows a **deliberate, versioned progression**:

- First make LLM testing deterministic
- Then expand the input/outpu space (multimodal)
- Then expand the system topology (agents, MCP, tasks)
- Finally, measure change scientifically (A/B testing and model modification)

The goal is to evolve from **LLMs as single functions** to **LLMs as full systems under test**.

---

## Phase 0 — MVP (v1.0)
**Goal:** Deterministic correctness testing for LLMs

### Features
- Robot Framework keyword library
- Core keywords:
  - `Ask LLM`
  - `Grade Answer`
- Binary scoring (pass / fail)
- Strict JSON-only grader contracts
- Local (Ollama) and remote model support
- CI-compatible execution

### Scope Constraints
- Text-only prompts
- Single model under test
- No model mutation
- No agent interaction

### Success Criteria
- Tests pass/fail reliably
- Grader output is machine-validated
- Results are repeatable across runs
- Suitable for regression testing

---

## Phase 1 — Structured Evaluation (v1.1–v1.2)
**Goal:** Move beyond binary correctness while preserving determinism

### Features
- Multi-score rubrics (0–5, categorical)
- Partial credit support
- Confidence scoring
- Tolerance rules (numeric ranges, equivalence)
- Canonical answer normalization

### Example Rubric Output
```json
{
  "accuracy": 4,
  "clarity": 3,
  "reasoning": 5
}
````

### Outcomes

* More expressive evaluation
* Better signal for regressions
* Foundation for later A/B testing

---

## Phase 2 — Multimodal Model Testing (v2.0)

**Goal:** Validate LLM behavior across multiple modalities

### Features

* Image + text prompt support
* Audio + text prompt support (ASR / TTS)
* Multimodal grading using LLMs
* Modality-aware grading rubrics
* Deterministic artifact capture and replay:

  * Images
  * Audio
  * Metadata

### Use Cases

* Image understanding and reasoning
* OCR validation
* Caption generation accuracy
* Multimodal instruction-following
* Input/output alignment testing

### Constraints

* Artifacts must be versioned
* Tests must be replayable
* Grading remains structured and machine-verifiable

---

## Phase 3 — MCP, Multi-Agent, and Task Execution (v3.0)

**Goal:** Test coordinated AI systems, not just single models

### Features

* MCP (Model Context Provider) integration
* Multi-model chat orchestration
* Cross-model interaction testing
* Agent-to-agent communication validation
* Task execution framework for non-LLM workloads
* Robot Framework task primitives:

  * Run task
  * Validate output
  * Chain task → LLM → task

### Demo Deliverables

* MCP server reference implementation
* GitLab Merge Request review bot demo:

  * LLM-generated code review comments
  * Policy-aware approvals
  * Deterministic grading of review quality

### Outcomes

* LLMs treated as distributed systems
* Unified testing of AI + automation workloads
* Foundation for enterprise workflows

---

## Phase 4 — Model Modification & A/B Evaluation Pipelines (v4.0)

**Goal:** Measure the impact of model changes scientifically

### Features

* A/B testing framework for LLMs
* Prompt vs model comparison pipelines
* Automated dataset replay
* Statistical comparison of results
* Regression gating thresholds for CI

### Model Modification Support

* Prompt mutation pipelines
* Adapter / LoRA workflows
* Fine-tuning job orchestration
* Artifact versioning:

  * Models
  * Prompts
  * Datasets
  * Evaluation results

### Outcomes

* Quantifiable improvement measurement
* Safe iteration on model changes
* CI-enforced quality gates for AI systems

---

## Long-Term Vision

`robotframework-chat` becomes a **full AI systems testing platform** capable of validating:

* Single LLMs
* Multimodal AI systems
* Agent swarms and orchestrated workflows
* MCP-driven enterprise AI platforms
* Continuous model evolution with regression protection

---

## Roadmap Principles

* Determinism before intelligence
* Testing before training
* Automation before dashboards
* Regression detection over anecdotal evaluation
* AI systems should be testable, repeatable, and auditable
