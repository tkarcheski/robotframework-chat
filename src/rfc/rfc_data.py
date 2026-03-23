"""Centralized RFC_DATA structured log message emission.

All keyword libraries should use ``emit_rfc_data()`` instead of
manually formatting ``RFC_DATA:key:value`` strings.  This ensures
the prefix is consistent and prevents silent data loss from typos.

``RFC_DATA_PREFIX`` is the single source of truth for the structured
data prefix.  :class:`~rfc.base_listener.BaseListener` imports it
for parsing; keyword libraries use :func:`emit_rfc_data` for emission.
"""

from robot.api import logger  # type: ignore

# Single source of truth for the structured data prefix.
RFC_DATA_PREFIX: str = "RFC_DATA:"


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
