*** Settings ***
Documentation     Shared keywords for code review tests.
...
...               Wraps CodeReviewKeywords with assertion helpers.

Library           rfc.code_review_keywords.CodeReviewKeywords    WITH NAME    CR

*** Keywords ***
Find Bug And Pass
    [Documentation]    Ask LLM to find a bug and assert expected keywords are in the response.
    [Arguments]    ${code}    ${description}    ${keywords}    ${language}=Python    ${min_score}=0.5
    ${result}=    CR.Ask LLM To Find Bug
    ...    code=${code}
    ...    bug_description=${description}
    ...    required_keywords=${keywords}
    ...    language=${language}
    ...    min_score=${min_score}
    CR.Assert Code Review Passed    ${result}    label=${description}
    Log    ${result}[reason]
    RETURN    ${result}

Classify Bug And Pass
    [Documentation]    Ask LLM to classify bug type and assert the classification matches.
    [Arguments]    ${code}    ${expected_type}    ${language}=Python
    ${result}=    CR.Ask LLM To Classify Bug
    ...    code=${code}
    ...    expected_bug_type=${expected_type}
    ...    language=${language}
    Should Be True    ${result}[passed]
    ...    Bug classification failed — got ${result}[actual_bug_type], expected ${expected_type}
    Log    ${result}[reason]
    RETURN    ${result}

Suggest Fix And Pass
    [Documentation]    Ask LLM to fix code and assert expected fix tokens appear.
    [Arguments]    ${code}    ${fix_keywords}    ${language}=Python    ${min_score}=0.5
    ${result}=    CR.Ask LLM To Suggest Fix
    ...    code=${code}
    ...    expected_fix_keywords=${fix_keywords}
    ...    language=${language}
    ...    min_score=${min_score}
    CR.Assert Code Review Passed    ${result}    label=fix suggestion
    Log    ${result}[reason]
    RETURN    ${result}
