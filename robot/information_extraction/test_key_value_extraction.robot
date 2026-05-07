*** Settings ***
Documentation     Key-value pair extraction tests.
...
...               Verifies the LLM can read structured facts from unstructured
...               prose (product specs, company profiles) and reproduce them
...               in its response.  Graded by substring recall — no LLM grader.

Resource          information_extraction.resource
Default Tags      information_extraction    key_value    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Extract Product Specifications
    [Documentation]    Find RAM, storage, and price values in a product description.
    [Tags]    product    specs
    Extract Key Values And Pass    ${KV_EXTRACTION_SCENARIOS}[0]

Extract Company Profile Facts
    [Documentation]    Find founding year, HQ city, and CEO name in a company profile.
    [Tags]    company    profile
    Extract Key Values And Pass    ${KV_EXTRACTION_SCENARIOS}[1]
