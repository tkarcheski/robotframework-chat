"""Committed-up-front tests: test_subtract fails until the agent fixes the bug."""

import unittest

from calculator import add, multiply, subtract


class TestCalculator(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_subtract(self):
        self.assertEqual(subtract(5, 3), 2)

    def test_multiply(self):
        self.assertEqual(multiply(4, 3), 12)


if __name__ == "__main__":
    unittest.main()
