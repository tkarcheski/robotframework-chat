"""Visible test: the invoice total must render dollars via the shared interface.

This is the committed red baseline: it fails on the seed (money.format_amount
emits raw cents) and passes once the shared interface renders dollars.
"""

import unittest

from invoice import invoice_total


class TestInvoiceTotal(unittest.TestCase):
    def test_renders_dollars(self):
        self.assertEqual(invoice_total(500), "Total: $5.00")


if __name__ == "__main__":
    unittest.main()
