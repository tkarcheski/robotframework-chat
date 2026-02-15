# robotframework-chat — Project Roadmap

This roadmap follows a **deliberate, versioned progression**:

- First make LLM testing deterministic
- Then expand the evaluation layer (structured grading)
- Then expand the input/output space (multimodal)
- Then expand the system topology (agents, MCP, tasks)
- Finally, measure change scientifically (A/B testing and model comparison)

The goal is to evolve from **LLMs as single functions** to **LLMs as full
systems under test**.

---

## Phase 0 — MVP (v1.0) ✓ Complete

**Goal:** Deterministic correctness testing for LLMs

### Delivered

- Robot Framework keyword library (`src/rfc/`)
- Core keywords: `Ask LLM`, `Grade Answer`, `Wait For LLM`
- Binary scoring (pass / fail) with strict JSON-only grader contracts
- Ollama client with polling, model discovery, and health checks
- CI-compatible execution (GitLab CI with child pipelines)
- Three listeners always active: DbListener, CiMetadataListener,
  OllamaTimestampListener
- SQLite and PostgreSQL dual-backend result archiving
- Pre-run modifier for dynamic model-aware test filtering

---

## Phase 0.5 — Infrastructure & Observability ✓ Complete

**Goal:** Full pipeline automation and result visualization

### Delivered

- **Dynamic pipeline generation** from `config/test_suites.yaml`
  — regular, dynamic (manual), and scheduled (hourly) modes
- **Ollama network discovery** — scan subnets for Ollama nodes,
  enumerate models, generate per-node/per-model CI jobs
- **Apache Superset stack** — PostgreSQL 16, Redis 7, Superset 4.1.1
  with auto-bootstrapped dashboard (6 charts, 3 datasets)
- **Dashboard control panel** — Dash-based UI for running and
  controlling multiple Robot Framework test suites simultaneously
- **Test result import** — post-hoc import from `output.xml` files
- **CI metadata capture** — commit, branch, pipeline URL, runner info
- **Model metadata registry** — `robot/ci/models.yaml` with release
  dates, parameters, capabilities, and hardware requirements

### Pipeline model strategy

See [PIPELINES.md](PIPELINES.md) for the full pipeline strategy. In short:

- **Regular pipeline** runs on the smallest viable model to verify the
  testing system works
- **Dynamic / scheduled pipelines** test every available model for
  actual evaluation and comparison

---

## Phase 1 — Structured Evaluation (v1.1–v1.2) — In Progress

**Goal:** Move beyond binary correctness while preserving determinism

### Delivered

- Docker-based code execution with configurable CPU, memory, and
  network isolation
- Container profiles: MINIMAL, STANDARD, PERFORMANCE
- Python, Node.js, and shell command execution in containers
- LLM-in-Docker testing with container lifecycle management
- Safety testing suite: prompt injection, role switching, system
  extraction, boundary violation detection
- Regex-based safety grading with confidence scoring

### Remaining

- Multi-score rubrics (0–5, categorical dimensions)
- Partial credit support
- General confidence scoring (beyond safety domain)
- Tolerance rules (numeric ranges, equivalence matching)
- Canonical answer normalization

### Example Rubric Output
```json
{
  "accuracy": 4,
  "clarity": 3,
  "reasoning": 5
}
```

---

## Phase 1.5 — Superset & Reporting — In Progress

**Goal:** Comprehensive test result visualization and automated reporting

### Delivered

| Feature | Status |
|---------|--------|
| Auto-bootstrapped Superset dashboard | ✓ |
| Pass Rate Over Time (line chart) | ✓ |
| Model Comparison — Pass Rate (bar chart) | ✓ |
| Test Results Breakdown (pie chart) | ✓ |
| Test Suite Duration Trend (line chart) | ✓ |
| Recent Test Runs (table) | ✓ |
| Failures by Test Name (bar chart) | ✓ |
| PostgreSQL + Redis + Superset Docker stack | ✓ |
| Remote deploy via CI (`deploy-superset` stage) | ✓ |

### Planned

- **GitLab wiki page generation** — pipeline results published as
  wiki pages for lightweight visibility without Superset
- Cross-filtering and drill-down capabilities in dashboards
- Model regression alerts (threshold-based notifications)
- Per-model trend dashboards (auto-generated per discovered model)
- Data retention policies and automatic cleanup of old runs
- Scheduled dashboard refresh and export

---

## Phase 1.5 — LLM Manager

**Goal:** Unified management and testing of multiple LLMs simultaneously

### Multi-Model Configuration

- Define multiple LLM endpoints in a single configuration file
- Support model variants (temperature, max_tokens, system prompts)
- Named model aliases for routing
- Docker-based LLM deployment with resource isolation

### Parallel Execution

- Send same prompt to multiple models concurrently
- Compare responses side-by-side in test output
- Aggregate grading across multiple models
- Statistical analysis of model agreement

### Model Routing & Selection

- Tag-based model selection (e.g., `model=coding` selects codellama)
- Fallback chains when models are unavailable
- A/B testing support between model versions
- Load balancing across model replicas

### Container-Native LLM Testing

- Run LLMs in Docker containers with configurable resources
- CPU, memory, scratch disk, and network isolation
- Per-test and suite-level LLM container lifecycle management

### New Keywords

```robot
*** Keywords ***
Ask Multiple LLMs
    [Arguments]    ${prompt}    ${models}=llama3,mistral,codellama
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

---

## Phase 2 — Multimodal Model Testing (v2.0)

**Goal:** Validate LLM behavior across multiple modalities

### Features

- Image + text prompt support
- Audio + text prompt support (ASR / TTS)
- Multimodal grading using LLMs
- Modality-aware grading rubrics
- Deterministic artifact capture and replay (images, audio, metadata)

### Use Cases

- Image understanding and reasoning
- OCR validation
- Caption generation accuracy
- Multimodal instruction-following
- Input/output alignment testing

### Constraints

- Artifacts must be versioned
- Tests must be replayable
- Grading remains structured and machine-verifiable

---

## Phase 3 — MCP, Multi-Agent, and Task Execution (v3.0)

**Goal:** Test coordinated AI systems, not just single models

### Features

- MCP (Model Context Protocol) integration
- Multi-model chat orchestration
- Cross-model interaction testing
- Agent-to-agent communication validation
- Task execution framework for non-LLM workloads
- Robot Framework task primitives:
  - Run task
  - Validate output
  - Chain task → LLM → task

### Demo Deliverables

- MCP server reference implementation
- GitLab Merge Request review bot demo:
  - LLM-generated code review comments
  - Policy-aware approvals
  - Deterministic grading of review quality

### Outcomes

- LLMs treated as distributed systems
- Unified testing of AI + automation workloads
- Foundation for enterprise workflows

---

## Phase 4 — Model Modification & A/B Evaluation Pipelines (v4.0)

**Goal:** Measure the impact of model changes scientifically

### Features

- A/B testing framework for LLMs
- Prompt vs model comparison pipelines
- Automated dataset replay
- Statistical comparison of results
- Regression gating thresholds for CI

### Model Modification Support

- Prompt mutation pipelines
- Adapter / LoRA workflows
- Fine-tuning job orchestration
- Artifact versioning (models, prompts, datasets, evaluation results)

### Outcomes

- Quantifiable improvement measurement
- Safe iteration on model changes
- CI-enforced quality gates for AI systems

---

## Long-Term Vision

`robotframework-chat` becomes a **full AI systems testing platform**
capable of validating:

- Single LLMs
- Multimodal AI systems
- Agent swarms and orchestrated workflows
- MCP-driven enterprise AI platforms
- Continuous model evolution with regression protection

---

## Roadmap Principles

See [AGENTS.md — Core Philosophy](AGENTS.md#core-philosophy) for the
project's foundational principles. The roadmap additionally follows
these sequencing rules:

- Testing before training
- Automation before dashboards
- Regression detection over anecdotal evaluation
- AI systems should be testable, repeatable, and auditable
