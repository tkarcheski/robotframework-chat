"""Receipt rendering -- a second consumer of the same money.format_amount interface."""

from money import format_amount


def receipt_line(cents):
    return "Paid: " + format_amount(cents)
