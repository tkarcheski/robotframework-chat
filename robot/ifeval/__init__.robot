*** Settings ***
Name              IFEval Tests
Documentation     Instruction Following Evaluation (IFEval) Test Suite
...
...               Tests local Ollama models on strict instruction-following prompts
...               (e.g. "respond in exactly 3 sentences", "use bullet points only").
...               All checks are fully deterministic Python constraint checkers —
...               no LLM judge is used for grading.

Resource          ifeval.resource
Resource          ../resources/llm_setup.resource

Suite Setup       Verify LLM Available

Force Tags        ifeval    tier:1    verify:python
