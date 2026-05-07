*** Settings ***
Documentation     Organization-name extraction tests.
...
...               Verifies the LLM can list every organization mentioned in
...               a passage.  Graded by substring recall — no LLM grader.

Resource          information_extraction.resource
Default Tags      information_extraction    ner    organization    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Extract Merger News Organizations
    [Documentation]    Extract four organizations from a merger announcement.
    [Tags]    multi_entity    finance
    Extract Entities And Pass    ${ORG_EXTRACTION_SCENARIOS}[0]
