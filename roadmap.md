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
- **Docker-based Code Execution** - In Development
  - Configurable CPU, memory, and network isolation
  - Python, Node.js, and shell command execution
  - Read-only filesystems for security
  - Resource limits enforcement
- **LLM-in-Docker Testing** - In Development
  - Run Ollama in containers with custom resources
  - Multi-model comparison framework
  - Container lifecycle management via Robot

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
* Secure, isolated code execution environment

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

## Feature Wish List — LLM Manager

**Status:** Planned for Phase 1.5
**Goal:** Unified management and testing of multiple LLMs simultaneously

### Multi-Model Configuration
* Define multiple LLM endpoints in single configuration file
* Support model variants (temperature, max_tokens, system prompts)
* Named model aliases (e.g., "fast" → gpt-3.5-turbo, "accurate" → gpt-4)
* Docker-based LLM deployment with resource isolation

### Parallel Execution
* Send same prompt to multiple models concurrently
* Compare responses side-by-side in test output
* Aggregate grading across multiple models
* Statistical analysis of model agreement

### Model Routing & Selection
* Tag-based model selection (e.g., `model=coding` selects codellama)
* Fallback chains when models are unavailable
* A/B testing support between model versions
* Load balancing across model replicas

### Container-Native LLM Testing
* Run LLMs in Docker containers with configurable resources
* CPU, memory, scratch disk, and network isolation
* Per-test LLM container lifecycle management
* Suite-level LLM container sharing

### New Keywords
```robot
*** Keywords ***
Ask Multiple LLMs
    [Arguments]    ${prompt}    ${models}=gpt-4,claude-3,llama3
    ${responses}=    LLM.Ask Multiple LLMs    ${prompt}    ${models}
    RETURN    ${responses}

Compare LLM Responses
    [Arguments]    ${responses}
    ${comparison}=    LLM.Compare LLM Responses    ${responses}
    Log    Best model: ${comparison}[best_model]
    RETURN    ${comparison}

Select Model By Capability
    [Arguments]    ${capability}=coding
    ${model}=    LLM.Select Model    ${capability}
    LLM.Set LLM Model    ${model}
```

### Example Usage
```robot
*** Test Cases ***
Compare Code Generation Models (IQ:130)
    ${responses}=    Ask Multiple LLMs    Write a Python quicksort
    ...    models=codellama,gpt-4,claude-3-opus

    ${comparison}=    Compare LLM Responses    ${responses}
    Should Not Be Equal    ${comparison}[best_model]    ${None}

    Log    Winner: ${comparison}[best_model] with score ${comparison}[best_score]
```

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
