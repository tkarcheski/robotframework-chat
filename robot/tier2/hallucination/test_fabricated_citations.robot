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
