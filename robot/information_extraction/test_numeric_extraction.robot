*** Settings ***
Documentation     Numeric fact extraction tests.
...
...               Verifies the LLM can find a specific number in a passage
...               when asked a direct question.  Graded by exact value match
...               after comma/unit normalisation — no LLM grader.

Resource          information_extraction.resource
Default Tags      information_extraction    numeric    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Extract Employee Count From Company Report
    [Documentation]    Find the current employee headcount in an annual report snippet.
    [Tags]    count    business
    Extract Numeric Fact And Pass    ${NUMERIC_EXTRACTION_SCENARIOS}[0]

Extract Revenue Figure From Annual Report
    [Documentation]    Find the total revenue (millions) in a financial report snippet.
    [Tags]    finance
    Extract Numeric Fact And Pass    ${NUMERIC_EXTRACTION_SCENARIOS}[1]

Extract Peak Temperature From Experiment Log
    [Documentation]    Find the peak temperature reading in an experiment log.
    [Tags]    science
    Extract Numeric Fact And Pass    ${NUMERIC_EXTRACTION_SCENARIOS}[2]
