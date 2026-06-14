"""Tests for the provider-budget run planner (#510)."""

from __future__ import annotations

from pathlib import Path

from rfc.budget_scheduler import (
    Job,
    LeftoverStore,
    coverage_summary,
    plan_within_budget,
)


def _jobs(*pairs: tuple[str, str]) -> list[Job]:
    return [Job(model=m, suite=s) for m, s in pairs]


# ── plan_within_budget ──────────────────────────────────────────────────


def test_plans_all_when_budget_fits() -> None:
    pending = _jobs(("a", "math"), ("a", "safety"))
    today, deferred = plan_within_budget(pending, remaining=100, cost_per_job=15)
    assert today == pending
    assert deferred == []


def test_defers_overflow_in_order() -> None:
    pending = _jobs(("a", "s1"), ("a", "s2"), ("a", "s3"))
    # remaining 35, cost 15 -> only 2 jobs fit (30), 1 deferred
    today, deferred = plan_within_budget(pending, remaining=35, cost_per_job=15)
    assert today == pending[:2]
    assert deferred == pending[2:]


def test_zero_remaining_defers_everything() -> None:
    pending = _jobs(("a", "s1"))
    today, deferred = plan_within_budget(pending, remaining=0, cost_per_job=15)
    assert today == []
    assert deferred == pending


def test_cost_larger_than_budget_defers_all() -> None:
    pending = _jobs(("a", "s1"))
    today, deferred = plan_within_budget(pending, remaining=10, cost_per_job=15)
    assert today == []
    assert deferred == pending


# ── coverage_summary ─────────────────────────────────────────────────────


def test_coverage_summary_partial() -> None:
    # 40 total cells, 10 done today, 30 still pending, 10/day -> ETA 3 days
    line = coverage_summary(total=40, planned_today=10, remaining=30, per_day=10)
    assert "25%" in line  # 10/40
    assert "3" in line  # ceil(30/10)


def test_coverage_summary_complete() -> None:
    line = coverage_summary(total=40, planned_today=40, remaining=0, per_day=10)
    assert "100%" in line
    assert "complete" in line.lower()


def test_coverage_summary_zero_total_is_safe() -> None:
    line = coverage_summary(total=0, planned_today=0, remaining=0, per_day=10)
    assert "100%" in line or "no " in line.lower()


# ── LeftoverStore ─────────────────────────────────────────────────────────


def test_leftover_roundtrip(tmp_path: Path) -> None:
    store = LeftoverStore(tmp_path / "leftover.json")
    jobs = _jobs(("a", "s1"), ("b", "s2"))
    store.save("openrouter", jobs)
    assert store.load("openrouter") == jobs


def test_leftover_is_per_provider(tmp_path: Path) -> None:
    store = LeftoverStore(tmp_path / "leftover.json")
    store.save("openrouter", _jobs(("a", "s1")))
    store.save("groq", _jobs(("b", "s2")))
    assert store.load("openrouter") == _jobs(("a", "s1"))
    assert store.load("groq") == _jobs(("b", "s2"))


def test_leftover_missing_provider_is_empty(tmp_path: Path) -> None:
    assert LeftoverStore(tmp_path / "leftover.json").load("nope") == []


def test_leftover_corrupt_file_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "leftover.json"
    path.write_text("{ not json")
    assert LeftoverStore(path).load("openrouter") == []


def test_leftover_save_failopen(tmp_path: Path) -> None:
    store = LeftoverStore(
        tmp_path / "missing" / "deep" / "leftover.json", create_parents=False
    )
    store.save("openrouter", _jobs(("a", "s1")))  # must not raise
    assert store.load("openrouter") == []
