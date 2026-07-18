#!/bin/sh
# Negative variant: fixes the behaviour (all() instead of any()) but keeps the
# quadratic list scan. The answers are correct, so the visible tests pass; the
# hidden perf contract's comparison budget is blown.
set -e
cat > membership.py <<'PYEOF'
"""Quadratic membership check for the tier:4 perf-guard scenario."""


def all_present(needles, haystack):
    return all(needle in haystack for needle in needles)
PYEOF
