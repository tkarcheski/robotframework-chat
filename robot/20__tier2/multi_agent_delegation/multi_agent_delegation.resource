*** Settings ***
Documentation     Shared wiring for the multi-agent delegation-abuse suite.
...               Reuses the safety grader keywords; supplies delegation-attack
...               prompts from this suite's own variables file.

Resource          ../safety/safety.resource
Variables         ${CURDIR}/variables/delegation_attacks.yaml

*** Keywords ***
Run Delegation Attack Test
    [Documentation]    A delegation-laundered request must be refused exactly as
    ...                a direct one would be: the model must not treat a claimed
    ...                inter-agent message as exempt from its safety boundary.
    [Arguments]    ${attack}
    Run Jailbreak Test Case    ${attack}[payload]    ${attack}[name]
