"""Tests for rfc.constants — single source of truth for shared constants."""

from rfc.constants import DEFAULT_TIMEOUT


def test_default_timeout_value() -> None:
    assert DEFAULT_TIMEOUT == 5400


def test_default_timeout_type() -> None:
    assert isinstance(DEFAULT_TIMEOUT, int)
