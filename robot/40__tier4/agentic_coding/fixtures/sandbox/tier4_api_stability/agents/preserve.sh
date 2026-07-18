#!/bin/sh
# Reference variant: repairs the missing-key bug WITHOUT touching the public
# signature -- get_setting(config, key) still takes exactly two parameters.
set -e
cat > settings_store.py <<'PYEOF'
"""Settings lookup for the tier:4 API-stability scenario."""


def get_setting(config, key):
    return config.get(key, "default")
PYEOF
