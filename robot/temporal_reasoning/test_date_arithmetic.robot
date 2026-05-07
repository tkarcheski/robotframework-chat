*** Settings ***
Documentation     Date arithmetic and calendar reasoning tests.
...
...               Verifies that the LLM can compute date offsets, count days
...               between two dates, and identify the correct day of the week.
...               All expected answers are precomputed with Python datetime
...               and checked via deterministic substring matching (tier:1).

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    date_arithmetic    tier:1    verify:python

Test Timeout      2 minutes

*** Test Cases ***

Date Offset — 90 Days After January 1 2024
    [Documentation]    Compute a date 90 days forward from a fixed anchor.
    ...                Expected: March 31 2024 (verified with Python datetime).
    Assert Temporal Exact Match
    ...    What date is exactly 90 days after January 1, 2024? Reply with only the date in Month Day Year format.
    ...    March 31

Date Offset — 45 Days After February 1 2024
    [Documentation]    Compute a date offset crossing a leap-year February boundary.
    ...                Expected: March 17 2024 (2024 is a leap year; verified with Python datetime).
    Assert Temporal Exact Match
    ...    What date is exactly 45 days after February 1, 2024? Reply with only the date in Month Day Year format.
    ...    March 17

Date Offset — 2 Weeks After March 15 2024
    [Documentation]    Compute a 14-day offset — should be straightforward for any model.
    ...                Expected: March 29 2024.
    Assert Temporal Exact Match
    ...    What date is exactly 2 weeks (14 days) after March 15, 2024? Reply with only the date in Month Day Year format.
    ...    March 29

Date Offset — 100 Days After October 1 2023
    [Documentation]    Cross a year boundary: 100 days after Oct 1 2023 = Jan 9 2024.
    Assert Temporal Exact Match
    ...    What date is exactly 100 days after October 1, 2023? Reply with only the date in Month Day Year format.
    ...    January 9

Days Between Two Dates — January To July 2024
    [Documentation]    Count days between Jan 1 2024 and Jul 4 2024.
    ...                Expected: 185 days (verified with Python datetime).
    Assert Temporal Exact Match
    ...    How many days are there between January 1, 2024 and July 4, 2024? Count the days but do not include the start date. Reply with only the number.
    ...    185

Days Between Two Dates — April To December 2024
    [Documentation]    Count days between Apr 1 and Dec 31 2024.
    ...                Expected: 274 days.
    Assert Temporal Exact Match
    ...    How many days are there between April 1, 2024 and December 31, 2024? Count the days but do not include the start date. Reply with only the number.
    ...    274

Day Of Week — July 4 2024
    [Documentation]    Identify the day of the week for a specific date.
    ...                Expected: Thursday (verified with Python datetime).
    Assert Temporal Exact Match
    ...    What day of the week was July 4, 2024? Reply with only the day name.
    ...    Thursday

Day Of Week — January 1 2025
    [Documentation]    Identify the day of the week for New Year's Day 2025.
    ...                Expected: Wednesday (verified with Python datetime).
    Assert Temporal Exact Match
    ...    What day of the week is January 1, 2025? Reply with only the day name.
    ...    Wednesday

Relative Day Offset — Wednesday Plus 10 Days
    [Documentation]    Compute a day-of-week offset without an anchor date.
    ...                Wednesday + 10 days = Saturday (10 mod 7 = 3; Wed + 3 = Sat).
    Assert Temporal Exact Match
    ...    If today is Wednesday and an event is exactly 10 days from now, what day of the week will the event occur? Reply with only the day name.
    ...    Saturday

Leap Year Awareness — February Days In 2024
    [Documentation]    Verify the model knows 2024 is a leap year with 29 days in February.
    Assert Temporal Exact Match
    ...    How many days does February 2024 have? Reply with only the number.
    ...    29

Non-Leap Year Awareness — February Days In 2023
    [Documentation]    Verify the model knows 2023 is not a leap year (28 days in February).
    Assert Temporal Exact Match
    ...    How many days does February 2023 have? Reply with only the number.
    ...    28
