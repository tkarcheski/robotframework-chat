# robotfrmework-chat

## Dev Setup (Initial)

Install the following tools:

* ollama
* astral-uv
* python 3.12

Install the default model
```bash
ollama pull llama3
```

## Running Robot (Example)

```bash
uv run robot -d results robot/math
```

## Installing Precommit/Ruff

```bash
pre-commit install
pre-commit run --all-files
```


## Overview
`robotframework-chat` is a Robot Framework–based test harness for **systematically testing Large Language Models (LLMs)** using **LLMs as both the system under test and as automated graders**.

The project starts from first principles: deterministic tasks, strict grading, and machine-verifiable results. It is designed to scale from trivial correctness checks (e.g., math) to complex behavioral, multimodal, and multi-agent system evaluations.

This repository is intentionally **infrastructure-first**: it focuses on repeatability, auditability, and CI integration rather than ad-hoc prompt experiments.

---

## Core Philosophy

- **LLMs are software** → they should be tested like software
- **Judging must be constrained** → graders return structured data only
- **Determinism first, intelligence later**
- **Robot Framework as the orchestration layer**
- **CI-native, regression-focused**

---

## Key Capabilities

### Current / MVP
- Prompt LLMs from Robot Framework
- Grade LLM responses using LLM-based judges
- Strict JSON grading contracts
- Binary and rubric-based scoring
- Model-agnostic execution (local or remote)
- CI-friendly execution and reporting

### Planned
- Multimodal testing (image, audio, text)
- MCP-based multi-agent orchestration
- Task execution beyond LLMs
- A/B testing of modified models

---

## Architecture (MVP)

Robot Framework Test
|
v
Python Keyword Library (robotframework-chat)
|
+--> LLM Under Test
|
+--> LLM Grader (JSON-only)


### Why this works
- Robot Framework provides **orchestration, assertions, and reporting**
- Python provides **API control, validation, and extensibility**
- LLM graders provide **semantic evaluation at scale**

---

## Example Test (MVP)

```robot
*** Test Cases ***
LLM Can Do Basic Math
    ${answer}=    Ask LLM    What is 2 + 2?
    ${score}    ${reason}=    Grade Answer    What is 2 + 2?    4    ${answer}
    Should Be Equal As Integers    ${score}    1
```

# Repository Structure

```css
robotframework-chat/
├── README.md
├── ROADMAP.md
├── src/
│   └── rfc/
│       └── LLMTestLib.py
├── robot/
│   └── tests/
│       └── llm_math.robot
├── requirements.txt
└── docs/
```

# Why Robot Framework?

* Proven in hardware, embedded, and systems testing
* Clear separation of intent and implementation
* Excellent logs and reports
* CI-native
* Familiar to QA and systems engineers
