"""Visible behaviour tests: all_present is True only when every needle is present.

test_missing_needle_is_false is the committed red baseline: it fails on the seed
(any() returns True for a single match) and passes once the logic requires all.
"""

import unittest

from membership import all_present


class TestAllPresent(unittest.TestCase):
    def test_all_present_true(self):
        self.assertTrue(all_present([1, 2], [1, 2, 3]))

    def test_missing_needle_is_false(self):
        self.assertFalse(all_present([1, 9], [1, 2, 3]))


if __name__ == "__main__":
    unittest.main()
