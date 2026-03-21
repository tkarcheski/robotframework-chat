*** Settings ***
Documentation     Task management test suite. Tests LLM abilities for prioritization, decomposition, scheduling, and triage.
Resource          ../resources/llm_setup.resource
Test Tags        task_management    tier:2    verify:llm
Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished Task Management Test Suite
