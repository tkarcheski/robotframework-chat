"""Superset configuration for robotframework-chat.

Connects Superset's own metadata DB to the same PostgreSQL instance
that holds the Robot Framework test results.  All credentials are
read from environment variables set by docker-compose.
"""

import os

_pg_user = os.getenv("POSTGRES_USER", "rfc")
_pg_pass = os.getenv("POSTGRES_PASSWORD", "rfc")
_pg_db = os.getenv("POSTGRES_DB", "rfc")

# Superset metadata database (its own tables, same PG instance)
SQLALCHEMY_DATABASE_URI = f"postgresql://{_pg_user}:{_pg_pass}@postgres:5432/{_pg_db}"

SECRET_KEY = os.getenv(
    "SUPERSET_SECRET_KEY",
    "robotframework-chat-superset-secret-change-me",
)

# Redis cache
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_HOST": "redis",
    "CACHE_REDIS_PORT": 6379,
    "CACHE_REDIS_DB": 0,
}

DATA_CACHE_CONFIG = CACHE_CONFIG

# Feature flags
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}

# Disable CSRF for API-only usage (dashboard bootstrap)
WTF_CSRF_ENABLED = False

# Allow embedding in iframes
SESSION_COOKIE_SAMESITE = "Lax"
ENABLE_CORS = True
