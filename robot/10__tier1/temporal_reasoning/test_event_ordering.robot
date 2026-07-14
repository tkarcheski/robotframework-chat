*** Settings ***
Documentation     Event Ordering Tests
...
...               Presents the LLM with four historical events labeled A–D
...               and asks which occurred EARLIEST. The letter from the first
...               line of the response is compared to the expected ground truth.
...
...               Events are chosen from well-established history so that
...               the correct answer is unambiguous and publicly documented.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    event_ordering    tier:1    verify:python
Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***
Battle Of Waterloo Is Earliest Of Four 20th-Century Milestones
    [Documentation]    Waterloo (1815) predates Wright Brothers (1903), Apollo 11 (1969),
    ...                and Berlin Wall fall (1989).
    [Tags]    tier:1    verify:python    history
    Assert Earliest Event Correct    ${EVENT_ORDERING_CASES}[0]

Einstein Relativity Is Earliest Scientific Discovery
    [Documentation]    Special relativity (1905) predates penicillin (1928),
    ...                DNA double helix (1953), and Human Genome Project (2003).
    [Tags]    tier:1    verify:python    history    science
    Assert Earliest Event Correct    ${EVENT_ORDERING_CASES}[1]

Telephone Is Earliest Technological Invention
    [Documentation]    Bell's telephone (1876) predates the Wright Brothers (1903),
    ...                Sputnik (1957), and the World Wide Web (1991).
    [Tags]    tier:1    verify:python    history    technology
    Assert Earliest Event Correct    ${EVENT_ORDERING_CASES}[2]

US Declaration Of Independence Is Earliest American Event
    [Documentation]    Declaration of Independence (1776) predates the Civil War start
    ...                (1861), Gettysburg Address (1863), and transcontinental railroad (1869).
    [Tags]    tier:1    verify:python    history    american_history
    Assert Earliest Event Correct    ${EVENT_ORDERING_CASES}[3]

IBM PC Is Earliest Computing Event
    [Documentation]    IBM PC (1981) predates the World Wide Web proposal (1991),
    ...                Google founding (1998), and iPhone release (2007).
    [Tags]    tier:1    verify:python    history    computing
    Assert Earliest Event Correct    ${EVENT_ORDERING_CASES}[4]
