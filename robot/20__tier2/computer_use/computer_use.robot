*** Settings ***
Documentation     Computer-use substrate v0: browser actions as dispatchable tools.
...
...               Drives a scripted tool-call sequence -- open page, read as
...               markdown, click, assert -- entirely through ToolSchema
...               dispatch (Dispatch Computer Use Call), with a screenshot
...               archived per step. The page is a local file:// fixture so the
...               suite is hermetic (no external sites). Browser tests skip when
...               the playwright extra / rfbrowser binaries are unavailable; the
...               schema test runs regardless.
...
...               Browser-library keywords (New Browser / Close Browser) are
...               invoked via variable indirection so the suite parses under
...               `robot --dryrun` even when the Browser library is absent; the
...               test bodies themselves only call this project's dispatch
...               keywords.
Library           rfc.computer_use_keywords.ComputerUseKeywords
Library           Collections

Test Tags         computer_use    axis:none

Suite Setup       Import Browser Or Flag Unavailable
Suite Teardown    Close Browser If Available

*** Variables ***
${FIXTURE_URL}          file://${CURDIR}/fixtures/test_page.html
${BROWSER_AVAILABLE}    ${TRUE}

*** Test Cases ***
Computer Use Tools Expose Browser Actions
    [Documentation]    The tool schemas cover the five browser actions and
    ...                declare their required fields. No browser needed.
    [Tags]    tier:1    verify:python    schema
    @{names}=    Get Computer Use Tool Names
    List Should Contain Value    ${names}    browser_new_page
    List Should Contain Value    ${names}    browser_click
    List Should Contain Value    ${names}    browser_type_text
    List Should Contain Value    ${names}    browser_read_markdown
    List Should Contain Value    ${names}    browser_screenshot
    Length Should Be    ${names}    5
    @{tools}=    Get Computer Use Tools
    Log    Tool schemas: ${tools}

Scripted Tool Call Sequence Through Dispatch
    [Documentation]    open page -> read markdown -> click -> assert, every step
    ...                dispatched via ToolSchema, screenshot archived per step.
    [Tags]    tier:1    verify:python    browser    computer_use_flow
    Skip If Browser Unavailable

    # Step 1: open the local fixture page.
    ${r_open}=    Dispatch Computer Use Call    browser_new_page
    ...    {"url": "${FIXTURE_URL}"}
    Assert Tool Call Succeeded    ${r_open}
    Archive Step Screenshot    01_opened

    # Step 2: read the page as markdown and assert its initial state.
    ${r_read1}=    Dispatch Computer Use Call    browser_read_markdown
    Assert Tool Call Succeeded    ${r_read1}
    Should Contain    ${r_read1}[output]    Computer Use Fixture
    Should Contain    ${r_read1}[output]    Status: ready

    # Step 3: click the button through dispatch.
    ${r_click}=    Dispatch Computer Use Call    browser_click    {"selector": "id=go"}
    Assert Tool Call Succeeded    ${r_click}
    Archive Step Screenshot    02_clicked

    # Step 4: re-read markdown and assert the click took effect.
    ${r_read2}=    Dispatch Computer Use Call    browser_read_markdown
    Assert Tool Call Succeeded    ${r_read2}
    Should Contain    ${r_read2}[output]    Status: clicked
    Should Not Contain    ${r_read2}[output]    Status: ready

Type Text Through Dispatch
    [Documentation]    Typing into an input is dispatchable and reflected on the
    ...                page.
    [Tags]    tier:1    verify:python    browser    computer_use_flow
    Skip If Browser Unavailable
    ${r_open}=    Dispatch Computer Use Call    browser_new_page
    ...    {"url": "${FIXTURE_URL}"}
    Assert Tool Call Succeeded    ${r_open}
    ${r_type}=    Dispatch Computer Use Call    browser_type_text
    ...    {"selector": "id=note", "text": "hello agent"}
    Assert Tool Call Succeeded    ${r_type}
    Archive Step Screenshot    03_typed

*** Keywords ***
Import Browser Or Flag Unavailable
    [Documentation]    Import + launch Browser; flag unavailable instead of
    ...                failing so the schema test can still run. New Browser is
    ...                invoked indirectly so dryrun does not require the library.
    TRY
        Import Library    Browser
        ${new_browser}=    Set Variable    New Browser
        Run Keyword    ${new_browser}    chromium    headless=true
    EXCEPT    AS    ${error}
        Set Suite Variable    ${BROWSER_AVAILABLE}    ${FALSE}
        Log    Browser unavailable, browser tests will skip: ${error}    level=WARN
    END

Close Browser If Available
    [Documentation]    Close the browser only when it was actually launched;
    ...                the keyword name is indirected so dryrun stays library-free.
    IF    ${BROWSER_AVAILABLE}
        ${close_browser}=    Set Variable    Close Browser
        Run Keyword And Ignore Error    ${close_browser}
    END

Skip If Browser Unavailable
    [Documentation]    Skip the current test when the Browser library / binaries
    ...                are not installed (uv sync --extra playwright && rfbrowser init).
    IF    not ${BROWSER_AVAILABLE}
        Skip    Browser library not installed. Install with: uv sync --extra playwright && rfbrowser init
    END

Archive Step Screenshot
    [Documentation]    Capture a screenshot via ToolSchema dispatch, archived
    ...                under the Robot output dir per step.
    [Arguments]    ${label}
    ${result}=    Dispatch Computer Use Call    browser_screenshot
    ...    {"filename": "computer_use_${label}"}
    Assert Tool Call Succeeded    ${result}
    Log    ${result}[output]
