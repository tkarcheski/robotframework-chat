#!/bin/sh
# Negative variant: patches the invoice consumer locally, bypassing the shared
# interface. The visible invoice test passes, but the untouched money interface
# still breaks the second consumer -- the hidden receipt contract fails.
set -e
cat > invoice.py <<'PYEOF'
"""Invoice rendering -- a consumer of the shared money.format_amount interface."""

from money import format_amount  # noqa: F401 -- retained but bypassed by the local patch


def invoice_total(cents):
    return "Total: " + f"${cents / 100:.2f}"
PYEOF
