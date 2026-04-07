*** Settings ***
Documentation     Format Compliance Test Suite
...
...               Tests LLM ability to follow output format constraints:
...               - Structured output: JSON, YAML, CSV with schema validation
...               - Length compliance: exact sentence count, word limits
...               - Negative constraints: forbidden word avoidance

Resource          format.resource
Resource          ../resources/llm_setup.resource

Suite Setup       Run Keywords    Verify LLM Available    AND    Setup Format Test Environment
Suite Teardown    Log    Format compliance test suite completed

Force Tags        format    regression
