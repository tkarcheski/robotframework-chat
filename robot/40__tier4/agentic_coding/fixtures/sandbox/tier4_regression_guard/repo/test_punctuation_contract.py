"""Committed red baseline (RFC-007 failing-first proof, #219).

The task is to refactor slugify to *also strip punctuation*. Before this test
existed, no committed test verified the task itself -- only the hidden
lowercasing contract -- so the seed was green at t=0 and a no-op agent scored
PASS. This test asserts the punctuation-stripping the task asks for; it FAILS on
the seeded textutils.py (which keeps punctuation) and PASSES only after the
refactor actually strips it, giving the scenario a genuine red baseline.
"""

import unittest

from textutils import slugify


class TestPunctuationContract(unittest.TestCase):
    def test_strips_punctuation(self):
        # Seed keeps the comma/bang -> "hello,-world!"; a correct refactor that
        # strips punctuation and lowercases yields "hello-world".
        self.assertEqual(slugify("Hello, World!"), "hello-world")


if __name__ == "__main__":
    unittest.main()
