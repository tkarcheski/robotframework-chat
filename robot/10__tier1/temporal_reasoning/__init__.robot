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
Resource          ../../resources/llm_setup.resource
Suite Setup       Verify LLM Available

# platinum: the highest-signal gate suite. Grading is fully deterministic (no
# judge), prompts are short, and the base model passes some tests outright while
# failing others — so a change can show up as either a gain or a regression. A
# suite everything already passes can only ever look worse.
Test Tags         gold    platinum
