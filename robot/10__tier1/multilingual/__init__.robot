*** Settings ***
Name              Multilingual Instruction Following
Documentation     Cross-Language Instruction Following Test Suite
...
...               Extends the IFEval pattern to non-English prompts.  Asks the
...               model for structured outputs in Spanish, German, or Japanese
...               and verifies the response follows the format even when the
...               instruction language differs from the response language.
...
...               Catches tokenizer-level quality gaps in smaller quantized
...               models — e.g. degraded BPE coverage of non-Latin scripts.

Resource          multilingual.resource
Resource          ../../resources/llm_setup.resource

Suite Setup       Verify LLM Available

Force Tags        multilingual    tier:1    verify:python
