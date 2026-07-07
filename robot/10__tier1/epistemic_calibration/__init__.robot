*** Settings ***
Documentation     Epistemic Calibration test suite.
...
...               Tests two key calibration failure modes in LLMs:
...
...               1. Uncertainty expression — the model should hedge when asked
...                  about inherently unknowable or random outcomes (dice rolls,
...                  future weather, lottery numbers).
...
...               2. Knowledge boundary acknowledgment — the model should
...                  acknowledge its training cutoff and inability to access
...                  real-time data (live scores, breaking news, current prices).
...
...               Calibrated models that express appropriate uncertainty are
...               safer in production: they don't mislead users with false
...               confidence about things they cannot possibly know.
...
...               All tests are Tier 1 (Robot + Python). Pass/fail is determined
...               by deterministic marker matching — no LLM grader involved.
Resource          ../../resources/llm_setup.resource
Suite Setup       Verify LLM Available
