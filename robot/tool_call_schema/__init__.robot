*** Settings ***
Name              Tool Call Schema Tests
Documentation     Tool/function-call schema accuracy test suite.
...
...               Verifies that the LLM emits correctly-typed tool calls:
...               required fields present, no extra fields, type-correct
...               values, enum-constrained fields restricted to allowed
...               values, and the right tool selected from ambiguous
...               signatures.

Resource          tool_call_schema.resource
Resource          ../resources/llm_setup.resource

Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished Tool Call Schema Test Suite

Force Tags        tool_call_schema    tier:1    verify:python
