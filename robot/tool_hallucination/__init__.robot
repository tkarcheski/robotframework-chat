*** Settings ***
Name              Tool Hallucination Tests
Documentation     Tool hallucination detection test suite.
...
...               Tests whether an LLM correctly selects only real tools
...               from a mixed list of real and fake tools.

Resource          tool_hallucination.resource
Resource          ../resources/llm_setup.resource

Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished Tool Hallucination Test Suite

Force Tags        tool_hallucination    tier:2    verify:llm
