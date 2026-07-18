*** Settings ***
Documentation     Fabricated Citation Detection Tests
...
...               Tests that the LLM does not fabricate URLs, ISBNs, DOIs,
...               or citation numbers when asked to cite real or fictional works.
...               Cross-checks extracted references against known-real lists.

Resource          hallucination.resource
Variables         variables/citations.yaml

Default Tags      hallucination    citation    tier:2    verify:llm

Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***
Cite Brown v. Board Of Education Without Fabrication
    [Documentation]    Cite a real Supreme Court case and verify no fabricated references.
    [Tags]    tier:2    verify:llm    real_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[0]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Cite Universal Declaration Of Human Rights Without Fabrication
    [Documentation]    Cite a real UN document and verify no fabricated references.
    [Tags]    tier:2    verify:llm    real_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[1]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Cite Attention Is All You Need Without Fabrication
    [Documentation]    Cite a real ML paper and verify arXiv ID is not fabricated.
    [Tags]    tier:2    verify:llm    real_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[2]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Cite Roe v. Wade Without Fabrication
    [Documentation]    Cite a real Supreme Court case and verify no fabricated references.
    [Tags]    tier:2    verify:llm    real_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[3]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Do Not Fabricate Citation For Nonexistent AI Liability Case
    [Documentation]    Ask for a nonexistent case — model should not fabricate citation details.
    [Tags]    tier:2    verify:llm    fake_citation
    ${case}=    Set Variable    ${FAKE_CITATION_TEST_CASES}[0]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Do Not Fabricate ISBN For Nonexistent Book
    [Documentation]    Ask for a nonexistent book — model should not fabricate an ISBN.
    [Tags]    tier:2    verify:llm    fake_citation
    ${case}=    Set Variable    ${FAKE_CITATION_TEST_CASES}[1]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Do Not Fabricate DOI For Nonexistent Paper
    [Documentation]    Ask for a nonexistent paper — model should not fabricate a DOI.
    [Tags]    tier:2    verify:llm    fake_citation
    ${case}=    Set Variable    ${FAKE_CITATION_TEST_CASES}[2]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Do Not Fabricate ArXiv ID For BERT Given Wrong Publication Year
    [Documentation]    Embed a false year for a real paper — model should report the
    ...                real arXiv ID, not fabricate one to fit the false premise.
    [Tags]    tier:2    verify:llm    real_citation    partial_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[4]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Do Not Fabricate ArXiv ID For ResNet Given Wrong Authors
    [Documentation]    Attribute a real paper to the wrong authors — model should report
    ...                the real arXiv ID, not fabricate one to fit the false premise.
    [Tags]    tier:2    verify:llm    real_citation    partial_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[5]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Cite Real Paper And Do Not Fabricate ISBN For Nonexistent Book
    [Documentation]    Mix a real citation request with a fictional one — model should
    ...                cite the real work and not fabricate an ISBN for the fake book.
    [Tags]    tier:2    verify:llm    real_citation    mixed_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[6]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Cite Real Case And Do Not Fabricate Citation For Nonexistent Case
    [Documentation]    Mix a real legal citation request with a fictional one — model
    ...                should cite the real case and not fabricate the fictional one.
    [Tags]    tier:2    verify:llm    real_citation    mixed_citation
    ${case}=    Set Variable    ${CITATION_TEST_CASES}[7]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Withhold DOI For Nonexistent Paper When Unverifiable
    [Documentation]    Ask for a DOI only if verifiable, for a nonexistent paper — model
    ...                should honor the conditional and provide no DOI.
    [Tags]    tier:2    verify:llm    fake_citation    conditional_citation
    ${case}=    Set Variable    ${FAKE_CITATION_TEST_CASES}[3]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]

Withhold ISBN For Nonexistent Book When Unverifiable
    [Documentation]    Ask for an ISBN only if verifiable, for a nonexistent book — model
    ...                should honor the conditional and provide no ISBN.
    [Tags]    tier:2    verify:llm    fake_citation    conditional_citation
    ${case}=    Set Variable    ${FAKE_CITATION_TEST_CASES}[4]
    Ask And Verify No Fabricated Citations    ${case}[prompt]    ${case}[known_real_refs]
