*** Settings ***
Documentation     Shared LLM availability verification for test suite setups.
...
...               Provides a pre-flight check that verifies the LLM provider is
...               online and the configured model is loaded / served. Suites
...               that depend on an external LLM should call
...               ``Verify LLM Available`` in their Suite Setup. If the provider
...               is offline or the model cannot be loaded, the suite is
...               *skipped* (not failed), so a cold-load that returns empty no
...               longer records false-positive test failures.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Variables ***
${LLM_VERIFY_TIMEOUT}    %{OLLAMA_TIMEOUT=5400}

*** Keywords ***
Verify LLM Available
    [Documentation]    Verify the provider is online and the model is ready.
    ...    Provider-aware: Ollama warms the model into VRAM and proves it emits
    ...    tokens; vLLM / OpenAI-compatible servers confirm the /models catalog
    ...    is reachable. On failure the suite is SKIPPED (ROBOT_SKIP_EXECUTION),
    ...    not failed — preventing false-positive results.
    ...    Timeout is read from OLLAMA_TIMEOUT env var (default: 5400s / 90 min).
    LLM.Ensure Model Ready    timeout=${LLM_VERIFY_TIMEOUT}
    Log    LLM verified: provider online and model ready.
