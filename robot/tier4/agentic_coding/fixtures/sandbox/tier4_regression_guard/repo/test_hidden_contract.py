"""Hidden regression guard: not mentioned in the task description.

A naive punctuation-stripping refactor that drops the lowercasing step
breaks this contract; the sandbox harness must surface the failure.
"""

import unittest

from textutils import slugify


class TestHiddenContract(unittest.TestCase):
    def test_lowercases_mixed_case_input(self):
        self.assertEqual(slugify("Hello World"), "hello-world")


if __name__ == "__main__":
    unittest.main()
