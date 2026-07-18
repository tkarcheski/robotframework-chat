#!/bin/sh
# Reference variant: fixes the behaviour AND keeps membership linear by probing a
# set once, so the hidden comparison-count budget holds.
set -e
cat > membership.py <<'PYEOF'
"""Linear membership check for the tier:4 perf-guard scenario."""


def all_present(needles, haystack):
    haystack_set = set(haystack)
    return all(needle in haystack_set for needle in needles)
PYEOF
