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
    ...                remove the throwaway workspace. The outcome maps every
    ...                teardown-visible ``${TEST STATUS}`` explicitly —
    ...                ``FAIL`` -> ``failed``, ``SKIP`` -> ``partial``,
    ...                ``PASS`` -> ``success`` — so neither a failed (#213) nor a
    ...                skipped-after-open (#254) live leg is mislabeled a success
    ...                in the ``agentic_harnesses`` spine. A bare else -> success
    ...                folds ``SKIP`` into ``success``, the #213 trap via the
    ...                skip branch.
    [Arguments]    ${ws}
    ${outcome}=    Set Variable If
    ...    "${TEST STATUS}" == "FAIL"    failed
    ...    "${TEST STATUS}" == "SKIP"    partial
    ...    success
    Run Keyword And Ignore Error    End Harness Session    outcome=${outcome}
    Remove Directory    ${ws}[path]    recursive=True
