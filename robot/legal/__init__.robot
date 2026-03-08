*** Settings ***
Documentation     Legal Document Analysis Test Suite
...
...               Tests LLM ability to analyze software agreements, focusing on:
...               - Needle-in-haystack: finding specific clauses buried in boilerplate
...               - Loophole detection: identifying contradictions, overreach, and imbalances

Resource          legal.resource

Suite Setup       Setup Legal Test Environment
Suite Teardown    Log    Legal document test suite completed

Force Tags        legal    software-agreement    regression    tier:2    verify:llm
