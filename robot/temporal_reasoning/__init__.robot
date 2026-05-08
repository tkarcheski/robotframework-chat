*** Settings ***
Documentation     Temporal Reasoning test suite.
...
...               Tests whether an LLM can:
...               - Order historical events correctly (Tier 1 — deterministic)
...               - Perform date and duration arithmetic (Tier 1 — deterministic)
...               - Resolve relative time expressions (Tier 1 — deterministic)
...               - Analyse and describe multi-event timelines (Tier 2 — LLM-graded)
...
...               Temporal reasoning is a well-documented weak spot for LLMs.
...               Failures here indicate the model conflates sequence with
...               causation, miscounts calendar units, or cannot chain
...               relative-time expressions into a consistent order.
