*** Settings ***
Documentation     Persona Consistency Tests
...
...               System-prompts the model as a specific persona, then sends
...               10 adversarial follow-up turns trying to break character.
...               Scores identity consistency across all turns using the
...               Grade Answer keyword via the persona grading pipeline.

Resource          persona.resource

Test Tags         persona    consistency    tier:2    verify:llm    axis:model

Test Timeout      250 minutes

*** Test Cases ***
Pirate Captain Under Pressure
    [Documentation]    Can the LLM maintain pirate captain persona across 10
    ...                increasingly forceful attempts to break character?
    [Tags]    pirate    severity:high    regression
    Run Persona Test    ${PERSONAS}[0]

Formal Academic Under Casual Pressure
    [Documentation]    Can the LLM maintain formal academic language when
    ...                bombarded with casual slang and emoji-laden messages?
    [Tags]    academic    severity:high    regression
    Run Persona Test    ${PERSONAS}[1]

Helpful Librarian vs Role Derailment
    [Documentation]    Can the LLM maintain librarian identity when pressured
    ...                to adopt completely different professional roles?
    [Tags]    librarian    severity:medium    regression
    Run Persona Test    ${PERSONAS}[2]

English-Only Persona Under Multilingual Pressure
    [Documentation]    Can the LLM maintain English-only output when addressed
    ...                in French, Spanish, Japanese, German, Russian, and Arabic?
    [Tags]    multilingual    severity:high    regression
    Run Persona Test    ${PERSONAS}[3]
