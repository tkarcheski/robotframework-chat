"""Invoice rendering -- a consumer of the shared money.format_amount interface."""

from money import format_amount


def invoice_total(cents):
    return "Total: " + format_amount(cents)
