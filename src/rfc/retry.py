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


def retry_on_transient(fn: Callable[[], T], *, max_retries: int) -> T:
    """Call *fn* with retry on transient HTTP errors.

    Catches ``ReadTimeout`` and ``ConnectionError``, applying exponential
    backoff (2, 4, 8, … seconds).  All other exceptions propagate immediately.

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
        except _TRANSIENT_EXCEPTIONS as exc:
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
                logger.error(
                    f"generate() failed after {attempt + 1} attempts: {exc}"
                )
    raise last_exception  # type: ignore[misc]
