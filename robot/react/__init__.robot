*** Settings ***
Name              ReAct Loop Tests
Documentation     ReAct (Reason + Act) loop test suite.
...
...               Tests multi-step reasoning where the LLM must call tools
...               and reach a final answer within a step budget.

Resource          react.resource
Resource          ../resources/llm_setup.resource

Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished ReAct Loop Test Suite

Force Tags        react    tier:2    verify:llm
