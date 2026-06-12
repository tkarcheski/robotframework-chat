"""Superset configuration for robotframework-chat.

Connects Superset's own metadata DB to the same PostgreSQL instance
that holds the Robot Framework test results.  All credentials are
read from environment variables set by docker-compose.
"""

import os

_pg_user = os.getenv("POSTGRES_USER", "rfc")
_pg_pass = os.getenv("POSTGRES_PASSWORD", "changeme")
_pg_db = os.getenv("POSTGRES_DB", "rfc")
_pg_port = os.getenv("POSTGRES_INTERNAL_PORT", "5432")

# Superset metadata database (its own tables, same PG instance)
SQLALCHEMY_DATABASE_URI = (
    f"postgresql://{_pg_user}:{_pg_pass}@postgres:{_pg_port}/{_pg_db}"
)

SECRET_KEY = os.getenv(
    "SUPERSET_SECRET_KEY",
    "robotframework-chat-superset-secret-change-me",
)

# Redis cache — metadata/filter cache (longer TTL is fine)
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_HOST": "redis",
    "CACHE_REDIS_PORT": 6379,
    "CACHE_REDIS_DB": 0,
}

# Data query cache — short TTL so new imports appear quickly.
# `make import` also flushes Redis automatically, but this ensures
# dashboards stay reasonably fresh even without explicit flushes.
DATA_CACHE_CONFIG = {
    **CACHE_CONFIG,
    "CACHE_DEFAULT_TIMEOUT": 30,
    "CACHE_KEY_PREFIX": "superset_data_",
}

# flask-limiter rate-limit state — in-memory by default, which resets on
# restart and isn't shared across workers (issue #414). DB 2 keeps it
# apart from the caches on DB 0.
RATELIMIT_STORAGE_URI = "redis://redis:6379/2"

# Feature flags
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}

# Disable CSRF for API-only usage (dashboard bootstrap)
WTF_CSRF_ENABLED = False

# Allow embedding in iframes
SESSION_COOKIE_SAMESITE = "Lax"
ENABLE_CORS = True

# ── Theme (Superset 6.0+ Ant Design v5 theming) ─────────────────────
# Goal: dark loads by default for everyone, but a light theme stays
# reachable via the in-app toggle. Superset uses THEME_DEFAULT as the
# initial theme and THEME_DARK as the alternate, so we *reverse* the usual
# assignment — dark is the default, light is the toggle target.
#
# Caveat: when both are set, Superset also enables OS prefers-color-scheme
# auto-switching, which this reversal inverts (an OS-dark client lands on
# the light alternate). That is acceptable here since dark-by-default is the
# intent. Set THEME_DARK = None to force dark with no toggle at all.
#
# The dark palette uses the project's TRON look: cyan primary and orange
# accent over a near-black background.
THEME_DEFAULT = {
    "algorithm": "dark",
    "token": {
        "colorPrimary": "#00dffc",
        "colorInfo": "#00dffc",
        "colorWarning": "#ff8c42",
        "colorBgBase": "#0a0a0f",
        "colorBgContainer": "#0d1117",
        "colorBgLayout": "#0a0a0f",
        "colorTextBase": "#e6f7ff",
        "fontFamily": "'Share Tech Mono', 'Courier New', monospace",
    },
}

THEME_DARK = {
    "algorithm": "default",
    "token": {
        "colorPrimary": "#00dffc",
    },
}

# Let admins manage system-wide themes from the Superset UI.
ENABLE_UI_THEME_ADMINISTRATION = True
