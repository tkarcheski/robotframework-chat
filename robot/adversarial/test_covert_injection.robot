*** Settings ***
Documentation     Covert Adversarial Prompt Injection Tests
...
...               Tests whether LLMs resist hidden instructions embedded in benign
...               questions using techniques like zero-width Unicode whitespace,
...               code comments, base64 encoding, and homoglyph substitution.
...
...               Unlike the overt injection tests in robot/safety/, these tests
...               embed the injection covertly so the model must resist instructions
...               that are not visually obvious in the prompt text.

Resource          adversarial.resource

Test Tags         adversarial    covert_injection    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***
Whitespace Zero-Width Injection Resistance
    [Documentation]    Can the LLM solve a math problem when "ignore instructions"
    ...                is encoded as zero-width Unicode characters within the prompt?
    [Tags]    whitespace    severity:critical    regression
    Run Covert Injection Test    ${COVERT_INJECTIONS}[0]

Comment-Style Code Injection Resistance
    [Documentation]    Can the LLM write correct code when an injection is hidden
    ...                inside code comments in the prompt?
    [Tags]    comment    severity:high    regression
    Run Covert Injection Test    ${COVERT_INJECTIONS}[1]

Base64-Wrapped Injection Resistance
    [Documentation]    Can the LLM answer a geography question when a base64-encoded
    ...                injection payload is appended to the prompt?
    [Tags]    base64    severity:high    regression
    Run Covert Injection Test    ${COVERT_INJECTIONS}[2]

Homoglyph Substitution Injection Resistance
    [Documentation]    Can the LLM solve arithmetic when an injection uses
    ...                Cyrillic homoglyphs to disguise the hidden instruction?
    [Tags]    homoglyph    severity:medium    regression
    Run Covert Injection Test    ${COVERT_INJECTIONS}[3]
