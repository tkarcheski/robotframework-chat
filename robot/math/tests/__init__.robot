*** Settings ***
Documentation     Math test suite. All tests in this directory and subdirectories are tagged with: math
Resource          ../../resources/llm_setup.resource
Test Tags        math    tier:2    verify:llm
Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished Math Test Suite
