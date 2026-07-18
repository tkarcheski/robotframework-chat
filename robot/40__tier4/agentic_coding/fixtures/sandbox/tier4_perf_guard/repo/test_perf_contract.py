"""Hidden performance contract: not mentioned in the task.

The task asks to fix the behaviour, but all_present must stay linear. Membership
is probed with counting sentinels whose __eq__ tallies comparisons; a quadratic
list scan blows the linear budget even when its answers are correct, while a
set-based lookup stays within it. The benchmark is a deterministic comparison
count, not wall-clock time, so the guard never flakes.
"""

import unittest

from membership import all_present


class Counter:
    """A value whose equality comparisons are counted class-wide."""

    comparisons = 0

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        Counter.comparisons += 1
        return isinstance(other, Counter) and self.value == other.value

    def __hash__(self):
        return hash(self.value)


class TestPerfContract(unittest.TestCase):
    def test_membership_stays_linear(self):
        size = 40
        haystack = [Counter(i) for i in range(size)]
        # Every needle is the last element, so a list scan pays the full width
        # each time (quadratic); a set lookup pays one comparison each (linear).
        needles = [Counter(size - 1) for _ in range(size)]
        Counter.comparisons = 0
        self.assertTrue(all_present(needles, haystack))
        linear_budget = 4 * (len(needles) + len(haystack))
        self.assertLessEqual(Counter.comparisons, linear_budget)


if __name__ == "__main__":
    unittest.main()
