"""Retry helper for transient HTTP errors."""

import time
from typing import Callable, TypeVar

import requests
from robot.api import logger

T = TypeVar("T")

_TRANSIENT_EXCEPTIONS = (
    requests.exceptions.ReadTimeout,
    requests.exceptions.ConnectionError,
)


def _is_rate_limited(exc: Exception) -> bool:
    """True when *exc* is an HTTPError for a 429 (rate-limit) response."""
    return (
        isinstance(exc, requests.exceptions.HTTPError)
        and exc.response is not None
        and exc.response.status_code == 429
    )


def retry_on_transient(fn: Callable[[], T], *, max_retries: int) -> T:
    """Call *fn* with retry on transient HTTP errors.

    Catches ``ReadTimeout``, ``ConnectionError``, and HTTP 429 rate limits
    (issue #507), applying exponential backoff (2, 4, 8, … seconds). All
    other exceptions propagate immediately; an exhausted 429 propagates so
    the caller can skip-and-log per CLAUDE.md.

    Args:
        fn: Zero-argument callable that returns a result or raises.
        max_retries: Number of retries after the initial attempt.

    Returns:
        The value returned by *fn*.

    Raises:
        The last transient exception if all attempts are exhausted.
    """
    last_exception: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            return fn()
        except (*_TRANSIENT_EXCEPTIONS, requests.exceptions.HTTPError) as exc:
            if isinstance(exc, requests.exceptions.HTTPError) and not _is_rate_limited(
                exc
            ):
                raise
            last_exception = exc
            if attempt < max_retries:
                delay = 2 ** (attempt + 1)
                logger.warn(
                    f"generate() attempt {attempt + 1} failed: {exc}. "
                    f"Retrying in {delay}s "
                    f"({max_retries - attempt} retries left)"
                )
                time.sleep(delay)
            else:
                logger.error(f"generate() failed after {attempt + 1} attempts: {exc}")
    raise last_exception  # type: ignore[misc]
