*** Settings ***
Documentation     Shared LLM availability verification for test suite setups.
...
...               Provides a pre-flight check that verifies the LLM endpoint is
...               reachable and the configured model can respond. Suites that
...               depend on an external LLM should call ``Verify LLM Available``
...               in their Suite Setup to fail fast with a clear error.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Variables ***
${LLM_VERIFY_TIMEOUT}    %{OLLAMA_TIMEOUT=5400}

*** Keywords ***
Verify LLM Available
    [Documentation]    Verify the LLM endpoint is reachable and the model responds.
    ...    Fails the suite with a fatal error if the LLM is not available,
    ...    preventing all tests in the suite from running.
    ...    Timeout is read from OLLAMA_TIMEOUT env var (default: 5400s / 90 min).
    LLM.Wait For LLM    timeout=${LLM_VERIFY_TIMEOUT}
    ${response}=    LLM.Ask LLM    Say hello in one word.
    Should Not Be Empty    ${response}    LLM returned empty response — model may not be loaded
    Log    LLM verified: model is loaded and responding.
