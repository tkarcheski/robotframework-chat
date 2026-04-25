*** Settings ***
Name              Accounting Tests
Documentation     Accounting and financial math test suite.
Resource          ../resources/llm_setup.resource
Test Tags        accounting    tier:2    verify:llm
Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished Accounting Test Suite
