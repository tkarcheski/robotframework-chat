*** Settings ***
Documentation     Person-name extraction tests.
...
...               Verifies the LLM can list every person mentioned in a
...               passage.  Graded by substring recall — no LLM grader.

Resource          information_extraction.resource
Default Tags      information_extraction    ner    person    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Extract Board Meeting Attendees
    [Documentation]    Extract five person names from a board meeting passage.
    [Tags]    multi_entity
    Extract Entities And Pass    ${PERSON_EXTRACTION_SCENARIOS}[0]

Extract Press Release Names
    [Documentation]    Extract three person names from a press release snippet.
    [Tags]    multi_entity
    Extract Entities And Pass    ${PERSON_EXTRACTION_SCENARIOS}[1]
