"""Hidden contract: a second consumer of the same interface, not named in the task.

The task only exercises the invoice path, but receipt_line reads the same
money.format_amount interface. A fix that patches invoice.py locally instead of
the shared interface leaves this second consumer broken; a fix at the interface
repairs both.
"""

import unittest

from receipt import receipt_line


class TestReceiptContract(unittest.TestCase):
    def test_renders_dollars(self):
        self.assertEqual(receipt_line(1234), "Paid: $12.34")


if __name__ == "__main__":
    unittest.main()
