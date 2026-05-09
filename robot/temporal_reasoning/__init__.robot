*** Settings ***
Documentation     Temporal Reasoning test suite.
...
...               Tests whether an LLM can correctly perform:
...               - Date arithmetic (days in months, quarters, years)
...               - Duration calculations (converting between time units)
...               - Event ordering (identifying the earliest of four historical events)
...
...               All tests are Tier 1 (Robot + Python). The LLM's numeric or
...               letter answer is extracted deterministically from the first line
...               of its response, with no LLM used as a grader.
Resource          ../resources/llm_setup.resource
Suite Setup       Verify LLM Available
