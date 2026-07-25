*** Settings ***
Documentation     Shared keywords for the LIVE canary session-degradation suite.
...               Imports the model-driven session driver
...               (``rfc.canary_keywords.SessionCanaryKeywords``) plus the pure
...               engine's assertion keywords (``rfc.canary.CanaryEngineKeywords``).
...               The LLM surface here is what makes the suite ``axis:model``.

Library           rfc.canary_keywords.SessionCanaryKeywords
Library           rfc.canary.CanaryEngineKeywords
Library           OperatingSystem
Library           Collections

*** Keywords ***
Require Canary Live Mode
    [Documentation]    Gate the whole suite on an explicit opt-in. The long
    ...                canary session spends real model time, so it never runs by
    ...                accident — set ``CANARY_LIVE=1`` to enable it. Skip-and-log
    ...                otherwise (CLAUDE.md skip-over-fail for external deps).
    ${live}=    Get Environment Variable    CANARY_LIVE    ${EMPTY}
    IF    '${live}' != '1'
        Skip    Set CANARY_LIVE=1 to run the live canary session-degradation suite
    END
