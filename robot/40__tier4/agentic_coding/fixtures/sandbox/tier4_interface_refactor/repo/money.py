"""Currency formatting shared across the billing modules (the core interface)."""


def format_amount(cents):
    # BUG: emits the raw cent count; should render dollars with two decimals.
    return f"${cents}"
