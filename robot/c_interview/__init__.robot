*** Settings ***
Name              C Interview Questions
Documentation     C programming interview question suite.
...
...               Tests LLM knowledge of pointers, memory management, core language
...               behavior, and POSIX threading concepts via Q&A grading.

Resource          ../resources/llm_setup.resource

Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished C Interview Question Suite

Test Tags         c-interview    tier:2    verify:llm
