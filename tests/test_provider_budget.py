"""Tests for the file-backed per-provider daily request counter (#515)."""

from __future__ import annotations

from pathlib import Path

from rfc.provider_budget import ProviderBudget


def test_spent_is_zero_before_any_record(tmp_path: Path) -> None:
    budget = ProviderBudget(tmp_path / "b.json", today="2026-06-13")
    assert budget.spent("openrouter") == 0


def test_record_accumulates(tmp_path: Path) -> None:
    budget = ProviderBudget(tmp_path / "b.json", today="2026-06-13")
    budget.record("openrouter")
    budget.record("openrouter", 3)
    assert budget.spent("openrouter") == 4


def test_counts_are_per_provider(tmp_path: Path) -> None:
    budget = ProviderBudget(tmp_path / "b.json", today="2026-06-13")
    budget.record("openrouter", 2)
    budget.record("groq", 5)
    assert budget.spent("openrouter") == 2
    assert budget.spent("groq") == 5


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    ProviderBudget(path, today="2026-06-13").record("openrouter", 7)
    # A fresh process (new instance) on the same day sees the prior count —
    # this is what lets the scheduler cap a multi-run day (#515).
    assert ProviderBudget(path, today="2026-06-13").spent("openrouter") == 7


def test_counts_reset_on_new_utc_day(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    ProviderBudget(path, today="2026-06-13").record("openrouter", 9)
    assert ProviderBudget(path, today="2026-06-14").spent("openrouter") == 0


def test_exhausted_at_limit(tmp_path: Path) -> None:
    budget = ProviderBudget(tmp_path / "b.json", today="2026-06-13")
    budget.record("openrouter", 999)
    assert not budget.exhausted("openrouter", 1000)
    budget.record("openrouter")
    assert budget.exhausted("openrouter", 1000)  # 1000 >= 1000


def test_zero_or_negative_limit_never_exhausts(tmp_path: Path) -> None:
    budget = ProviderBudget(tmp_path / "b.json", today="2026-06-13")
    budget.record("openrouter", 5)
    assert not budget.exhausted("openrouter", 0)  # 0 = unlimited


def test_remaining(tmp_path: Path) -> None:
    budget = ProviderBudget(tmp_path / "b.json", today="2026-06-13")
    budget.record("openrouter", 200)
    assert budget.remaining("openrouter", 1000) == 800
    budget.record("openrouter", 5000)
    assert budget.remaining("openrouter", 1000) == 0  # never negative


def test_record_failopen_on_unwritable_path(tmp_path: Path) -> None:
    # A broken counter must never crash a run (CLAUDE.md skip-and-log); it
    # degrades to "no cap" rather than aborting.
    bad = tmp_path / "nope" / "deep" / "b.json"  # parent dirs missing
    budget = ProviderBudget(bad, today="2026-06-13", create_parents=False)
    budget.record("openrouter")  # must not raise
    assert budget.spent("openrouter") == 0  # unreadable -> 0 (fail-open)


def test_corrupt_state_file_treated_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text("{ not json")
    budget = ProviderBudget(path, today="2026-06-13")
    assert budget.spent("openrouter") == 0
    budget.record("openrouter", 2)  # recovers and overwrites
    assert budget.spent("openrouter") == 2


def test_uses_current_utc_day_when_not_overridden(tmp_path, monkeypatch):
    # A long-running scheduler instance must see the date roll over at UTC
    # midnight, not freeze the date captured at construction (#515 review).
    import rfc.provider_budget as pb

    path = tmp_path / "b.json"
    budget = pb.ProviderBudget(path)  # no explicit today
    monkeypatch.setattr(pb, "_utc_today", lambda: "2026-06-13")
    budget.record("openrouter", 4)
    assert budget.spent("openrouter") == 4
    # clock crosses midnight -> the same instance now reads the new day fresh
    monkeypatch.setattr(pb, "_utc_today", lambda: "2026-06-14")
    assert budget.spent("openrouter") == 0


def test_concurrent_records_do_not_lose_updates(tmp_path):
    # Two writers racing on the shared file must not clobber each other's
    # increment (#515 review). flock serializes the read-modify-write.
    import threading

    path = tmp_path / "b.json"
    barrier = threading.Barrier(8)

    def worker():
        b = ProviderBudget(path, today="2026-06-13")
        barrier.wait()
        for _ in range(25):
            b.record("openrouter")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ProviderBudget(path, today="2026-06-13").spent("openrouter") == 200
