*** Settings ***
Documentation     Temporal Reasoning test suite.
...
...               Tests whether an LLM can reason correctly about time:
...               - Ordering pairs of historical events (BEFORE / AFTER)
...               - Performing date and time arithmetic
...               - Sequencing three events in chronological order
...
...               Temporal reasoning is a growing LLM use-case (scheduling
...               assistants, timeline analysis, project planning) and a known
...               model failure mode.  All tests use deterministic
...               Python-backed grading (Tier 1, verify:python).
