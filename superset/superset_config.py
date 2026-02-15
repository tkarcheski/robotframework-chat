"""Superset configuration for robotframework-chat.

Connects Superset's own metadata DB to the same PostgreSQL instance
that holds the Robot Framework test results.
"""

import os

# Superset metadata database (its own tables)
SQLALCHEMY_DATABASE_URI = "postgresql://rfc:rfc@postgres:5432/rfc"

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
