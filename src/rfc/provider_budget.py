"""File-backed per-provider daily request counter (issue #515).

``select_models_within_budget`` caps an external provider's daily spend by an
*upfront estimate* (n_suites x requests_per_suite_estimate). That cannot catch
real overshoot — LLM-judge retries, self-healing retries, and 429 re-attempts
all make more HTTP calls than the estimate, so a sweep can blow past the
provider's daily allowance in an uncontrolled order.

This adds the missing primitive: a *runtime* counter, persisted per provider
per UTC day, that the scheduler reads to hard-stop dispatching new (model,
suite) jobs once the day's spend reaches the configured budget, and that the
OpenAI-compatible client increments on each request.

State is a small JSON document ``{"date": "<UTC date>", "counts": {...}}``.
A new UTC day resets the counts. All I/O is best-effort: a broken or
unwritable counter degrades to "no cap" (fail-open) and logs, rather than
aborting a run (CLAUDE.md skip-and-log) — the estimate guard and 429 backoff
remain as backstops.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

try:
    import fcntl  # POSIX advisory file locking
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

#: Env var pointing the OpenAI client + scheduler at a shared counter file.
BUDGET_FILE_ENV = "RFC_PROVIDER_BUDGET_FILE"
#: Env var naming the provider whose requests the client should count.
PROVIDER_NAME_ENV = "RFC_PROVIDER_NAME"


def _utc_today() -> str:
    return datetime.now(UTC).date().isoformat()


class ProviderBudget:
    """Counts requests made per provider per UTC day, backed by a JSON file."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        today: str | None = None,
        create_parents: bool = True,
    ) -> None:
        self._path = Path(path)
        # An explicit ``today`` is frozen (tests); otherwise resolve the UTC
        # day on every read/write so a long sweep that crosses midnight sees
        # the count reset rather than freezing the construction-time date.
        self._today_override = today
        self._create_parents = create_parents

    def _day(self) -> str:
        return self._today_override or _utc_today()

    # ── reads ───────────────────────────────────────────────────────────

    def _parse(self, raw: str) -> dict[str, int]:
        """Today's counts from a raw file body (empty on new day / corrupt)."""
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("Provider budget file corrupt; treating as empty.")
            return {}
        if not isinstance(data, dict) or data.get("date") != self._day():
            return {}  # stale day (or malformed) -> fresh
        counts = data.get("counts")
        return counts if isinstance(counts, dict) else {}

    def _load_counts(self) -> dict[str, int]:
        """Return today's counts, or an empty dict on a new day / any error."""
        try:
            raw = self._path.read_text()
        except FileNotFoundError:
            return {}
        except OSError as exc:  # unreadable -> fail-open
            logger.warning("Provider budget unreadable (%s); treating as empty.", exc)
            return {}
        return self._parse(raw)

    def spent(self, provider: str) -> int:
        """Requests recorded for *provider* today (0 if none / unreadable)."""
        value = self._load_counts().get(provider, 0)
        return value if isinstance(value, int) and value > 0 else 0

    def remaining(self, provider: str, limit: int) -> int:
        """Requests left before *limit* (never negative)."""
        return max(0, limit - self.spent(provider))

    def exhausted(self, provider: str, limit: int) -> bool:
        """True when *provider* has reached *limit* today.

        ``limit <= 0`` means unlimited and never exhausts.
        """
        return limit > 0 and self.spent(provider) >= limit

    # ── writes ──────────────────────────────────────────────────────────

    @contextlib.contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        """Hold an exclusive cross-process lock for a read-modify-write.

        Without it, two subprocesses (or the scheduler + a subprocess) can both
        read the same count and write the same +1, losing an increment. A
        sidecar ``.lock`` file is flocked so the data file's atomic replace is
        preserved. No-ops where ``fcntl`` is unavailable (non-POSIX).
        """
        if fcntl is None:  # pragma: no cover - non-POSIX
            yield
            return
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with open(lock_path, "w") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def record(self, provider: str, n: int = 1) -> None:
        """Add *n* requests to *provider*'s count for today (best-effort)."""
        if n <= 0:
            return
        try:
            if self._create_parents:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._exclusive_lock():
                # Re-read inside the lock so concurrent writers serialize and
                # no increment is lost.
                counts = self._load_counts()
                counts[provider] = counts.get(provider, 0) + n
                payload = json.dumps({"date": self._day(), "counts": counts})
                # Write-then-replace so a reader never sees a partial file.
                tmp = self._path.with_suffix(self._path.suffix + ".tmp")
                tmp.write_text(payload)
                os.replace(tmp, self._path)
        except OSError as exc:  # unwritable -> fail-open (no cap, logged once)
            logger.warning("Provider budget unwritable (%s); not counting.", exc)


def from_env(today: str | None = None) -> ProviderBudget | None:
    """Build a :class:`ProviderBudget` from ``RFC_PROVIDER_BUDGET_FILE``.

    Returns ``None`` when the env var is unset, so callers can no-op when
    budget tracking is not configured.
    """
    path = os.getenv(BUDGET_FILE_ENV, "").strip()
    if not path:
        return None
    return ProviderBudget(path, today=today)


def record_env_request(n: int = 1) -> None:
    """Increment the env-configured provider's counter, if configured.

    Called by the OpenAI-compatible client per request. No-ops (never raises)
    when budget tracking env vars are absent.
    """
    budget = from_env()
    provider = os.getenv(PROVIDER_NAME_ENV, "").strip()
    if budget is None or not provider:
        return
    budget.record(provider, n)


__all__ = [
    "BUDGET_FILE_ENV",
    "PROVIDER_NAME_ENV",
    "ProviderBudget",
    "from_env",
    "record_env_request",
]
