*** Settings ***
Documentation     Key-value extraction tests.
...
...               Asks the LLM to extract the value of a specific attribute
...               (version number, temperature, count, license, port, country)
...               from a short text passage. The extracted value is verified
...               with case-insensitive Python substring matching, with numeric
...               comma normalisation (e.g. 2,847 matches 2847).
...               Tier 1 / verify:python.

Resource          extraction.resource

Default Tags      extraction    key_value    tier:1    verify:python
Test Timeout      2 minutes

*** Test Cases ***

Software Version Number
    [Documentation]    Extract the version number from a software release-notes header.
    [Tags]    tier:1    verify:python    key_value    software
    Assert Key Value Extracted Correctly    ${KEY_VALUE_SCENARIOS}[0]

Oven Temperature From Recipe
    [Documentation]    Extract the preheat temperature (°C) from a cooking recipe.
    [Tags]    tier:1    verify:python    key_value    numeric
    Assert Key Value Extracted Correctly    ${KEY_VALUE_SCENARIOS}[1]

Clinical Trial Participant Count
    [Documentation]    Extract the total number of participants from a trial description.
    [Tags]    tier:1    verify:python    key_value    numeric
    Assert Key Value Extracted Correctly    ${KEY_VALUE_SCENARIOS}[2]

Open Source License Type
    [Documentation]    Extract the license name from a software distribution notice.
    [Tags]    tier:1    verify:python    key_value    legal
    Assert Key Value Extracted Correctly    ${KEY_VALUE_SCENARIOS}[3]

Default Server Port Number
    [Documentation]    Extract the default port number from a developer documentation snippet.
    [Tags]    tier:1    verify:python    key_value    numeric
    Assert Key Value Extracted Correctly    ${KEY_VALUE_SCENARIOS}[4]

Company Headquarters Country
    [Documentation]    Extract the headquarters country from a corporate profile.
    [Tags]    tier:1    verify:python    key_value    location
    Assert Key Value Extracted Correctly    ${KEY_VALUE_SCENARIOS}[5]

Maximum Upload Size Limit
    [Documentation]    Extract the file size limit from a platform upload policy.
    [Tags]    tier:1    verify:python    key_value    numeric
    Assert Key Value Extracted Correctly    ${KEY_VALUE_SCENARIOS}[6]
