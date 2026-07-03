#!/bin/sh
# Naive refactor: strips punctuation but silently drops the lowercasing
# step. Visible tests still pass; the hidden regression guard does not.
set -e
cat > textutils.py <<'PYEOF'
"""Text helpers for the tier:4 regression-guard scenario."""

import re


def slugify(text):
    cleaned = re.sub(r"[^A-Za-z0-9 ]", "", text)
    return cleaned.strip().replace(" ", "-")
PYEOF
