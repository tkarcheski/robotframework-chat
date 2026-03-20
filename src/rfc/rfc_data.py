"""Centralized RFC_DATA structured log message emission.

All keyword libraries should use ``emit_rfc_data()`` instead of
manually formatting ``RFC_DATA:key:value`` strings.  This ensures
the prefix is consistent and prevents silent data loss from typos.

The canonical prefix is defined in :attr:`BaseListener.RFC_DATA_PREFIX
<rfc.base_listener.BaseListener.RFC_DATA_PREFIX>`.  This module
re-exports it for convenience so that keyword libraries do not need
to depend on the listener infrastructure.
"""

from robot.api import logger  # type: ignore

from .base_listener import BaseListener

# Re-exported from BaseListener for backward compatibility and convenience.
RFC_DATA_PREFIX: str = BaseListener.RFC_DATA_PREFIX


def emit_rfc_data(key: str, value: str) -> None:
    """Emit a structured RFC_DATA log message for listener capture.

    Args:
        key: Data key (must not be empty or contain colons).
        value: Data value (may contain colons).

    Raises:
        ValueError: If key is empty or contains a colon.
    """
    if not key:
        raise ValueError("RFC_DATA key must not be empty")
    if ":" in key:
        raise ValueError(f"RFC_DATA key must not contain ':': {key!r}")
    logger.info(f"{RFC_DATA_PREFIX}{key}:{value}")
