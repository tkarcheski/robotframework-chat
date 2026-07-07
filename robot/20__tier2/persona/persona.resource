*** Settings ***
Documentation     Shared keywords for persona consistency tests.
Library           rfc.persona_keywords.PersonaKeywords    WITH NAME    Persona
Variables         ${CURDIR}/variables/personas.yaml

*** Keywords ***
Run Persona Test
    [Documentation]    Run a full persona consistency test and assert the persona held.
    [Arguments]    ${persona_config}    ${min_score}=0.7
    ${result}=    Persona.Run Persona Consistency Test
    ...    ${persona_config}[system_prompt]
    ...    ${persona_config}[adversarial_turns]
    ...    ${persona_config}[persona_criteria]
    Persona.Assert Persona Maintained    ${result}    min_score=${min_score}
    Log    Persona '${persona_config}[name]': avg=${result}[avg_score], min=${result}[min_score]
