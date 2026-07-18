#!/bin/sh
# Negative variant: repairs the behaviour but WIDENS the public signature with a
# third parameter. The visible behaviour tests still pass; the hidden API
# contract (signature is exactly (config, key)) fails.
set -e
cat > settings_store.py <<'PYEOF'
"""Settings lookup for the tier:4 API-stability scenario."""


def get_setting(config, key, default="default"):
    return config.get(key, default)
PYEOF
