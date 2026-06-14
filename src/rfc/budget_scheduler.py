"""Budget-aware run planner for external providers (issue #510).

Free tiers are request/day-bound, so a full model×suite sweep rarely fits one
day. This planner takes the pending ``(model, suite)`` matrix plus a provider's
*remaining* daily budget (from the #515 runtime counter) and:

* selects the jobs that fit today (``plan_within_budget``),
* carries the remainder to the next run (``LeftoverStore``), and
* reports how much of the matrix is covered and the ETA to full coverage
  (``coverage_summary``).

The pieces are pure and file-backed (no network), so they unit-test cleanly;
``scripts/run_local_models.py`` wires them into the provider sweep.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    """One unit of provider work: run *suite* against *model*."""

    model: str
    suite: str


def plan_within_budget(
    pending: list[Job], remaining: int, cost_per_job: int
) -> tuple[list[Job], list[Job]]:
    """Split *pending* into (today, deferred) within *remaining* requests.

    Each job is estimated to cost ``cost_per_job`` requests. Jobs are taken in
    order until the next would exceed *remaining*; the rest are deferred to a
    later day. ``cost_per_job <= 0`` is treated as 1 to avoid div-by-zero.
    """
    per = max(1, cost_per_job)
    fits = max(0, remaining) // per
    return pending[:fits], pending[fits:]


def coverage_summary(
    total: int, planned_today: int, remaining: int, per_day: int
) -> str:
    """One-line coverage report: percent done and ETA to full coverage."""
    if total <= 0:
        return "coverage: no jobs in the matrix (100%)"
    pct = round(100 * planned_today / total)
    if remaining <= 0:
        return f"coverage: {pct}% planned today — matrix complete"
    eta_days = math.ceil(remaining / max(1, per_day))
    return (
        f"coverage: {pct}% planned today ({planned_today}/{total}); "
        f"{remaining} left, ETA ~{eta_days} day(s) at {max(1, per_day)}/day"
    )


class LeftoverStore:
    """Persists each provider's deferred ``(model, suite)`` jobs between runs."""

    def __init__(
        self, path: str | os.PathLike[str], *, create_parents: bool = True
    ) -> None:
        self._path = Path(path)
        self._create_parents = create_parents

    def _load_all(self) -> dict[str, list[list[str]]]:
        try:
            data = json.loads(self._path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError):
            logger.warning("Leftover store unreadable/corrupt; treating as empty.")
            return {}
        return data if isinstance(data, dict) else {}

    def load(self, provider: str) -> list[Job]:
        """Return *provider*'s deferred jobs (empty if none / unreadable)."""
        raw = self._load_all().get(provider) or []
        jobs: list[Job] = []
        for pair in raw:
            if isinstance(pair, list) and len(pair) == 2:
                jobs.append(Job(model=str(pair[0]), suite=str(pair[1])))
        return jobs

    def save(self, provider: str, jobs: list[Job]) -> None:
        """Persist *provider*'s deferred jobs (best-effort, fail-open)."""
        data = self._load_all()
        data[provider] = [[j.model, j.suite] for j in jobs]
        try:
            if self._create_parents:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("Leftover store unwritable (%s); not persisting.", exc)


__all__ = [
    "Job",
    "LeftoverStore",
    "coverage_summary",
    "plan_within_budget",
]
