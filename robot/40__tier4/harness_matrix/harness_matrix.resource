*** Settings ***
Documentation     Session-teardown keyword for the harness matrix suite (#173),
...               extracted so its outcome derivation is exercisable outside a
...               live run (#213). Robot test teardowns run even when the test
...               body fails, so the ``agentic_harnesses`` outcome must be
...               derived from ``${TEST STATUS}`` — a hardcoded ``success`` closes
...               a crashed or red live leg as a false success, and the spine is
...               read by #169/#164 to judge run outcomes.

Library           rfc.harness_keywords.HarnessKeywords
Library           OperatingSystem

*** Keywords ***
End Session And Cleanup
    [Documentation]    Close the session row with the run's real outcome and
    ...                remove the throwaway workspace. The outcome tracks
    ...                ``${TEST STATUS}`` (``FAIL`` -> ``failed``, else
    ...                ``success``) so a failed live leg is never mislabeled a
    ...                success in the ``agentic_harnesses`` spine (#213).
    [Arguments]    ${ws}
    ${outcome}=    Set Variable If    "${TEST STATUS}" == "FAIL"    failed    success
    Run Keyword And Ignore Error    End Harness Session    outcome=${outcome}
    Remove Directory    ${ws}[path]    recursive=True
