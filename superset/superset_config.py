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

# Feature flags
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}

# Disable CSRF for API-only usage (dashboard bootstrap)
WTF_CSRF_ENABLED = False

# Allow embedding in iframes
SESSION_COOKIE_SAMESITE = "Lax"
ENABLE_CORS = True
