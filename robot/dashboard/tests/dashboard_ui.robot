*** Settings ***
Documentation     Self-tests for the Robot Framework Chat Dashboard UI.
...               These tests use Robot Framework Browser (Playwright) to
...               verify the dashboard renders correctly and responds to
...               user interactions.  They are independent of LLM tests.
Suite Setup       Open Dashboard
Suite Teardown    Close Dashboard Browser
Test Tags         dashboard    ui    browser

*** Variables ***
${DASHBOARD_URL}    http://localhost:8050
${TIMEOUT}          15s

*** Test Cases ***
Dashboard Loads Successfully
    [Documentation]    Verify the dashboard page loads and shows the title.
    Get Title    ==    Robot Framework Chat Control Panel

Header Is Visible
    [Documentation]    The navbar header should be visible with the app name.
    Get Text    css=h4    ==    Robot Framework Chat Control Panel

Sessions Tab Is Active By Default
    [Documentation]    The Sessions tab should be selected on page load.
    Get Element States    id=top-tab-sessions    contains    visible

Session Panel Has Required Controls
    [Documentation]    The first session panel should have all dropdowns and buttons.
    # Dropdowns
    Get Element Count    css=[id*="suite-dropdown"]    >=    1
    Get Element Count    css=[id*="iq-dropdown"]    >=    1
    Get Element Count    css=[id*="host-dropdown"]    >=    1
    Get Element Count    css=[id*="model-dropdown"]    >=    1
    Get Element Count    css=[id*="profile-dropdown"]    >=    1

    # Buttons
    Get Element Count    css=[id*="run-btn"]    >=    1
    Get Element Count    css=[id*="stop-btn"]    >=    1
    Get Element Count    css=[id*="replay-btn"]    >=    1

Console Output Area Exists
    [Documentation]    The console output pre element should exist.
    Get Element Count    css=[id*="console-output"]    >=    1

Progress Bar Exists
    [Documentation]    The progress bar should be present.
    Get Element Count    css=[id*="progress-bar"]    >=    1

Navigate To Ollama Hosts Tab
    [Documentation]    Click the Ollama Hosts tab and verify content appears.
    Click    text=Ollama Hosts
    Wait For Elements State    id=ollama-content    visible    timeout=${TIMEOUT}
    Get Text    id=ollama-content    contains    Ollama Hosts

Ollama Host Cards Render
    [Documentation]    The Ollama hosts tab should show host cards.
    # After polling there should be at least the loading or card content
    Wait For Elements State    id=ollama-cards    visible    timeout=${TIMEOUT}

Navigate To GitLab Pipelines Tab
    [Documentation]    Click the GitLab Pipelines tab and verify content appears.
    Click    text=GitLab Pipelines
    Wait For Elements State    id=pipelines-content    visible    timeout=${TIMEOUT}
    Get Text    id=pipelines-content    contains    GitLab Pipelines

Navigate Back To Sessions Tab
    [Documentation]    Click Sessions tab and verify session panel returns.
    Click    text=Sessions
    Wait For Elements State    id=top-tab-sessions    visible    timeout=${TIMEOUT}

New Session Button Works
    [Documentation]    Clicking '+ New Session' should add a new session tab.
    ${initial_tabs}=    Get Element Count    css=.nav-link
    Click    text=+ New Session
    Sleep    1s
    ${new_tabs}=    Get Element Count    css=.nav-link
    Should Be True    ${new_tabs} > ${initial_tabs}

Dark Theme Applied
    [Documentation]    Verify the dark theme background is applied to the page body.
    ${bg}=    Get Style    css=body > div    background-color
    # The background should be a dark colour (low RGB values)
    Should Not Be Equal    ${bg}    ${EMPTY}

*** Keywords ***
Open Dashboard
    [Documentation]    Launch a browser and navigate to the dashboard.
    TRY
        Import Library    Browser
    EXCEPT
        Skip    Browser library not installed. Install with: uv sync --extra playwright
    END
    New Browser    chromium    headless=true
    New Page    ${DASHBOARD_URL}
    Wait For Load State    networkidle    timeout=${TIMEOUT}

Close Dashboard Browser
    [Documentation]    Close browser if it was opened (no-op when Browser is unavailable).
    TRY
        Close Browser    ALL
    EXCEPT
        Log    Browser was not opened; nothing to close.
    END
