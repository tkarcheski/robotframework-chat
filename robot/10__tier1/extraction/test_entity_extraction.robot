*** Settings ***
Documentation     Named entity extraction tests.
...
...               Asks the LLM to extract a specific entity (person, place,
...               date, organisation) from a short text passage. The extracted
...               value is verified with case-insensitive Python substring
...               matching — Tier 1 / verify:python.

Resource          extraction.resource

Default Tags      extraction    entity    tier:1    verify:python
Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***

CEO Name From Tech News
    [Documentation]    Extract the CEO's name from a company news paragraph.
    [Tags]    tier:1    verify:python    entity    person
    Assert Entity Extracted Correctly    ${ENTITY_SCENARIOS}[0]

City From Travel Review
    [Documentation]    Extract the city name from a first-person travel account.
    [Tags]    tier:1    verify:python    entity    location
    Assert Entity Extracted Correctly    ${ENTITY_SCENARIOS}[1]

Publication Year From Academic Citation
    [Documentation]    Extract the year a famous paper was published.
    [Tags]    tier:1    verify:python    entity    date
    Assert Entity Extracted Correctly    ${ENTITY_SCENARIOS}[2]

Conference City From Announcement
    [Documentation]    Extract the host city from a formal event announcement.
    [Tags]    tier:1    verify:python    entity    location
    Assert Entity Extracted Correctly    ${ENTITY_SCENARIOS}[3]

Primary Language From Job Posting
    [Documentation]    Extract the required programming language from a job description.
    [Tags]    tier:1    verify:python    entity    technology
    Assert Entity Extracted Correctly    ${ENTITY_SCENARIOS}[4]

Animal Species From Nature Report
    [Documentation]    Extract the studied species from a wildlife research summary.
    [Tags]    tier:1    verify:python    entity    science
    Assert Entity Extracted Correctly    ${ENTITY_SCENARIOS}[5]

University From Collaboration Notice
    [Documentation]    Extract the lead researcher's institution from a collaboration notice.
    [Tags]    tier:1    verify:python    entity    organisation
    Assert Entity Extracted Correctly    ${ENTITY_SCENARIOS}[6]
