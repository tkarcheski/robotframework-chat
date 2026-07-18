#!/bin/sh
# Reference variant: fixes the shared money.format_amount interface, so every
# consumer (invoice AND receipt) is repaired by the single edit.
set -e
cat > money.py <<'PYEOF'
"""Currency formatting shared across the billing modules (the core interface)."""


def format_amount(cents):
    return f"${cents / 100:.2f}"
PYEOF
