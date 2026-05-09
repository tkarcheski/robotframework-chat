*** Settings ***
Documentation     Chronological Sequence Ordering Tests
...
...               Tests whether an LLM can correctly order a mixed list of
...               dates, events, or named time periods in chronological order.
...
...               Grading: Tier 1 / verify:python — the response is checked
...               to confirm that the anchor_first item appears at a lower
...               character position than anchor_last (case-insensitive).
...               Both anchors must be present for the test to pass.
...               No LLM judge is involved.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    sequence    tier:1    verify:python
Test Timeout      3 minutes

*** Test Cases ***

Order Months Of The Year
    [Documentation]    Five months given out of order. February must precede November.
    [Tags]    tier:1    verify:python    months
    Assert Sequence Order Correct    ${SEQUENCE_SCENARIOS}[0]

Order Days Of The Week
    [Documentation]    Five weekdays given out of order. Monday must precede Saturday.
    [Tags]    tier:1    verify:python    weekdays
    Assert Sequence Order Correct    ${SEQUENCE_SCENARIOS}[1]

Order Project Milestones With Explicit Dates
    [Documentation]    Five milestones with explicit month/day dates given.
    ...                Tests date-based sorting without requiring historical knowledge.
    [Tags]    tier:1    verify:python    milestones
    Assert Sequence Order Correct    ${SEQUENCE_SCENARIOS}[2]

Order Historical Inventions By Date
    [Documentation]    Printing press, steam engine, telephone, internet in order.
    ...                All approximate dates provided in the prompt.
    [Tags]    tier:1    verify:python    history
    Assert Sequence Order Correct    ${SEQUENCE_SCENARIOS}[3]

Order Seasons In Calendar Year
    [Documentation]    Four seasons given out of order. Spring must precede Winter.
    [Tags]    tier:1    verify:python    seasons
    Assert Sequence Order Correct    ${SEQUENCE_SCENARIOS}[4]

Order Historical Events By Year
    [Documentation]    Four events with explicit years. French Revolution
    ...                (1789) must precede Berlin Wall fall (1989).
    [Tags]    tier:1    verify:python    history
    Assert Sequence Order Correct    ${SEQUENCE_SCENARIOS}[5]
