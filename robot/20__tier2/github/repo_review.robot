*** Settings ***
Documentation     Browser-based GitHub repository evaluation.
...               Visits the public GitHub repo and issues page, converts to
...               markdown, and asks the LLM to evaluate project health and
...               suggest improvements.
Library           rfc.browser_keywords.BrowserKeywords    WITH NAME    Page
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           String

Test Tags         browser    axis:model

Suite Setup       Import Browser Or Skip
Suite Teardown    Run Keyword And Ignore Error    Close Browser

*** Variables ***
${GITHUB_REPO_URL}      https://github.com/tkarcheski/robotframework-chat
${GITHUB_ISSUES_URL}    https://github.com/tkarcheski/robotframework-chat/issues

*** Test Cases ***
GitHub Repo Page Loads
    [Documentation]    Can the browser reach the public GitHub repo page?
    [Tags]    tier:0    verify:robot    github
    New Page    ${GITHUB_REPO_URL}
    Wait For Load State    networkidle    timeout=30s
    ${title}=    Get Title
    Should Contain    ${title}    robotframework-chat
    Log    Page title: ${title}

LLM Evaluates Repository Health
    [Documentation]    Does the LLM find the repo well-maintained and documented?
    [Tags]    tier:2    verify:llm    github    repo-health
    New Page    ${GITHUB_REPO_URL}
    Wait For Load State    networkidle    timeout=30s
    ${html}=    Get Page Source
    ${markdown}=    Page.Convert HTML To Markdown    ${html}
    Log    Repo markdown:\n${markdown}    level=DEBUG
    ${prompt}=    Page.Build Evaluation Prompt
    ...    ${markdown}
    ...    page_type=repository
    ...    context=This is the robotframework-chat project — an LLM benchmarking harness using Robot Framework. The default branch is claude-code-staging. Evaluate the README, recent activity, and overall project health.
    ${feedback}=    LLM.Ask LLM    ${prompt}
    Log    LLM Feedback: ${feedback}
    Should Not Be Empty    ${feedback}

LLM Reviews Open Issues
    [Documentation]    Does the LLM identify priority issues and suggest next actions?
    [Tags]    tier:2    verify:llm    github    issue-triage
    New Page    ${GITHUB_ISSUES_URL}
    Wait For Load State    networkidle    timeout=30s
    ${html}=    Get Page Source
    ${markdown}=    Page.Convert HTML To Markdown    ${html}
    Log    Issues markdown:\n${markdown}    level=DEBUG
    ${prompt}=    Page.Build Evaluation Prompt
    ...    ${markdown}
    ...    page_type=issues
    ...    context=This is the robotframework-chat issue tracker. Issues prefixed with 'claw:' are automated improvement tasks from the OpenClaw AI agent system. Focus on which issues to prioritize next.
    ${feedback}=    LLM.Ask LLM    ${prompt}
    Log    LLM Feedback: ${feedback}
    Should Not Be Empty    ${feedback}

GitHub Issues Count Is Reasonable
    [Documentation]    Are there a manageable number of open issues (not spiraling)?
    [Tags]    tier:0    verify:robot    github    issue-count
    New Page    ${GITHUB_ISSUES_URL}
    Wait For Load State    networkidle    timeout=30s
    ${html}=    Get Page Source
    ${markdown}=    Page.Convert HTML To Markdown    ${html}
    # Extract issue count from the page — GitHub shows "N Open" in the issues tab
    ${matches}=    Get Regexp Matches    ${markdown}    (\\d+)\\s+Open    1
    ${count}=    Get Length    ${matches}
    IF    ${count} > 0
        ${open_count}=    Convert To Integer    ${matches}[0]
        Log    Open issues: ${open_count}
        Should Be True    ${open_count} < 50
        ...    Too many open issues (${open_count}). Triage needed.
    ELSE
        Fail    Could not extract issue count from page. GitHub markup may have changed.
    END

*** Keywords ***
Import Browser Or Skip
    [Documentation]    Import Browser library; skip suite if playwright is not installed.
    TRY
        Import Library    Browser
    EXCEPT
        Skip    Browser library not installed. Install with: uv sync --extra playwright && rfbrowser init
    END
    New Browser    chromium    headless=true
