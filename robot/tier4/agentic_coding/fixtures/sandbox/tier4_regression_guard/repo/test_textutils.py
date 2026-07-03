"""Visible tests: these pass before and after either refactor variant."""

import unittest

from textutils import slugify


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("hello world"), "hello-world")

    def test_strips_whitespace(self):
        self.assertEqual(slugify("  hello world  "), "hello-world")


if __name__ == "__main__":
    unittest.main()
