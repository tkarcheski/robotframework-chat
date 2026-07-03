*** Settings ***
Documentation     Shared keywords and variables for meta-learning probe tests.

Library           rfc.meta_learning_keywords.MetaLearningKeywords

*** Variables ***
${SKILL_RETENTION_THRESHOLD}    0.5

*** Keywords ***
Test Skill And Assert Retained
    [Documentation]    Teach a skill, send distractor, test retention, assert score.
    [Arguments]    ${skill}    ${distractor}    ${test_prompt}    ${expected}    ${min_score}=${SKILL_RETENTION_THRESHOLD}
    ${result}=    Test Skill Retention    ${skill}    ${distractor}    ${test_prompt}    ${expected}
    Log    Score: ${result}[score]
    Log    Skill applied: ${result}[skill_applied]
    Log    Actual answer: ${result}[actual_answer]
    Should Be True    ${result}[score] >= ${min_score}    Skill retention score ${result}[score] below threshold ${min_score}
    RETURN    ${result}
