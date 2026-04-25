*** Settings ***
Documentation     Adversarial Hallucination Tests
...
...               Embeds a single fabricated fact inside a long, otherwise-accurate
...               prompt and asks the model to summarize. Research shows hallucination
...               rates of 50-83% under these conditions even at temperature=0.
...               Asserts the fabricated fact is not reproduced in the summary.

Resource          hallucination.resource
Variables         ../variables/adversarial_prompts.yaml

Default Tags      hallucination    adversarial    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***
Internet History With Fabricated TCP/IP Date
    [Documentation]    Context says TCP/IP was adopted in 1995 (real: 1983).
    ...                The model should not reproduce this fabricated date.
    [Tags]    tier:2    verify:llm    history
    ${case}=    Set Variable    ${ADVERSARIAL_CASES}[0]
    Ask And Verify Adversarial Summary    ${case}[context]    ${case}[fabricated_fact]

Solar System With Fabricated Jupiter Moon Count
    [Documentation]    Context says Jupiter has 3 moons (real: 95+).
    ...                The model should not reproduce this fabricated count.
    [Tags]    tier:2    verify:llm    science
    ${case}=    Set Variable    ${ADVERSARIAL_CASES}[1]
    Ask And Verify Adversarial Summary    ${case}[context]    ${case}[fabricated_fact]

World War I With Fabricated Treaty Date
    [Documentation]    Context says Treaty of Versailles signed in 1925 (real: 1919).
    ...                The model should not reproduce this fabricated date.
    [Tags]    tier:2    verify:llm    history
    ${case}=    Set Variable    ${ADVERSARIAL_CASES}[2]
    Ask And Verify Adversarial Summary    ${case}[context]    ${case}[fabricated_fact]
