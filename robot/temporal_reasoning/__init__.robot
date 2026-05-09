*** Settings ***
Documentation     Temporal Reasoning Tests
...
...               Tests whether an LLM can correctly order historical events
...               chronologically, calculate elapsed time between events, and
...               solve temporal word problems.
...
...               Temporal reasoning underpins emerging LLM use-cases such as
...               scheduling assistants, deadline trackers, and historical
...               analysis tools.
...
...               Sub-suites:
...               - test_sequence_ordering   (Tier 1, verify:python)
...               - test_duration_calculation (Tier 1, verify:python)
...               - test_temporal_word_problems (Tier 1, verify:python)
