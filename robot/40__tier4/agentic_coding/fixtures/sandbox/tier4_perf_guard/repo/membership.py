"""Membership check that is both wrong and quadratic for the tier:4 perf-guard scenario."""


def all_present(needles, haystack):
    # BUG: returns True when ANY needle is present; should require ALL of them.
    # It also scans the haystack as a list, which the hidden perf contract rejects.
    return any(needle in haystack for needle in needles)
