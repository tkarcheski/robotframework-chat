*** Settings ***
Documentation     Historical event sequencing and duration estimation tests.
...
...               Tests the LLM's ability to order historical events correctly
...               and reason about relative durations between them.
...               Graded by an LLM judge (tier:2) because phrasing of
...               correct answers varies.

Resource          temporal_reasoning.resource

Default Tags      temporal_reasoning    event_sequencing    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***

Apollo 11 Predates The Berlin Wall Fall
    [Documentation]    Apollo 11 landed July 20 1969; Berlin Wall fell Nov 9 1989.
    ...                The model must identify Apollo 11 as the earlier event.
    Assert Temporal Graded
    ...    Which of these two events happened first: the Apollo 11 moon landing, or the fall of the Berlin Wall? Reply with only the name of the earlier event.
    ...    Apollo 11 moon landing (1969) came before the fall of the Berlin Wall (1989)

US Independence Predates The French Revolution
    [Documentation]    US Declaration of Independence was 1776; French Revolution began 1789.
    Assert Temporal Graded
    ...    Which happened first: the signing of the US Declaration of Independence, or the beginning of the French Revolution? Reply with only the name of the earlier event.
    ...    US Declaration of Independence (1776) came before the French Revolution (1789)

World War II Ended Before The Korean War Started
    [Documentation]    WWII in Europe ended May 8 1945; Korean War began June 25 1950.
    Assert Temporal Graded
    ...    Which happened first: the end of World War II, or the beginning of the Korean War? Reply with only the name of the earlier event.
    ...    End of World War II (1945) came before the start of the Korean War (1950)

Three-Event Chronological Ordering
    [Documentation]    The model must correctly order three major events.
    ...                Correct order: French Revolution (1789) → abolition of US slavery (1865) → first moon landing (1969).
    Assert Temporal Graded
    ...    Place these three events in chronological order from earliest to latest: the first moon landing, the abolition of slavery in the United States, the beginning of the French Revolution. List them in order separated by commas.
    ...    French Revolution (1789) first, then abolition of US slavery (1865), then first moon landing (1969)
    ...    min_score=0.6

Duration Between Scientific Milestones
    [Documentation]    Ask the model to estimate the years between two scientific discoveries.
    ...                Penicillin discovered 1928; DNA structure determined 1953 — approximately 25 years.
    Assert Temporal Graded
    ...    Approximately how many years passed between Alexander Fleming's discovery of penicillin and Watson and Crick's determination of DNA's double-helix structure?
    ...    Approximately 25 years (penicillin discovered 1928, DNA structure 1953)
    ...    min_score=0.4

Century Identification
    [Documentation]    The model must correctly identify which century an event occurred in.
    ...                The Battle of Hastings was in 1066 — the 11th century.
    Assert Temporal Graded
    ...    In which century did the Battle of Hastings take place?
    ...    11th century (1066)
    ...    min_score=0.7
