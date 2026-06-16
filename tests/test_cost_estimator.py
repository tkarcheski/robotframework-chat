"""Tests for cost & usage telemetry (#511)."""

from __future__ import annotations

from pathlib import Path

from rfc.cost_estimator import (
    MonthlySpend,
    estimate_cost,
    load_pricing,
    load_pricing_table,
)


# ── pricing table ─────────────────────────────────────────────────────────


def test_load_pricing_parses_entries() -> None:
    pricing = load_pricing(
        {
            "pricing": {
                "openai/gpt-4o": {"input_per_mtok": 2.5, "output_per_mtok": 10.0},
            }
        }
    )
    assert pricing["openai/gpt-4o"] == (2.5, 10.0)


def test_load_pricing_empty_when_absent() -> None:
    assert load_pricing({}) == {}


# ── estimate_cost ─────────────────────────────────────────────────────────


def test_estimate_cost_uses_table() -> None:
    pricing = {"m": (2.0, 6.0)}  # $/Mtok in, out
    # 1,000,000 prompt tokens * $2 + 500,000 completion * $6 = 2 + 3 = 5
    assert estimate_cost("m", 1_000_000, 500_000, pricing) == 5.0


def test_estimate_cost_unknown_model_is_free() -> None:
    # A free-tier or unlisted model costs nothing — the current providers are
    # all free tiers (#511).
    assert estimate_cost("gpt-oss-120b", 10_000, 10_000, {}) == 0.0


def test_estimate_cost_zero_tokens() -> None:
    assert estimate_cost("m", 0, 0, {"m": (2.0, 6.0)}) == 0.0


# ── load_pricing_table (file loader) ──────────────────────────────────────


def test_load_pricing_table_reads_file(tmp_path: Path) -> None:
    cfg = tmp_path / "local_models.yaml"
    cfg.write_text(
        "pricing:\n"
        "  openai/gpt-4o:\n"
        "    input_per_mtok: 2.5\n"
        "    output_per_mtok: 10.0\n"
    )
    pricing = load_pricing_table(cfg)
    assert pricing["openai/gpt-4o"] == (2.5, 10.0)


def test_load_pricing_table_missing_file_is_empty(tmp_path: Path) -> None:
    # Fail-open: an unreadable/absent config never aborts a run (#511).
    assert load_pricing_table(tmp_path / "does-not-exist.yaml") == {}


# ── MonthlySpend ──────────────────────────────────────────────────────────


def test_monthly_spend_accumulates(tmp_path: Path) -> None:
    spend = MonthlySpend(tmp_path / "s.json", month="2026-06")
    spend.record(1.50)
    spend.record(0.25)
    assert spend.spent() == 1.75


def test_monthly_spend_resets_each_month(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    MonthlySpend(path, month="2026-06").record(5.0)
    assert MonthlySpend(path, month="2026-07").spent() == 0.0


def test_monthly_spend_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    MonthlySpend(path, month="2026-06").record(3.0)
    assert MonthlySpend(path, month="2026-06").spent() == 3.0


def test_over_threshold(tmp_path: Path) -> None:
    spend = MonthlySpend(tmp_path / "s.json", month="2026-06")
    spend.record(15.0)
    assert not spend.over_threshold(cap_usd=20.0, fraction=0.8)  # 15 < 16
    spend.record(1.5)
    assert spend.over_threshold(cap_usd=20.0, fraction=0.8)  # 16.5 >= 16


def test_over_threshold_zero_cap_never_alarms(tmp_path: Path) -> None:
    spend = MonthlySpend(tmp_path / "s.json", month="2026-06")
    spend.record(100.0)
    assert not spend.over_threshold(cap_usd=0.0, fraction=0.8)


def test_monthly_spend_record_failopen(tmp_path: Path) -> None:
    spend = MonthlySpend(
        tmp_path / "missing" / "deep" / "s.json", month="2026-06", create_parents=False
    )
    spend.record(5.0)  # must not raise
    assert spend.spent() == 0.0


def test_monthly_spend_corrupt_file_is_zero(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text("{ not json")
    assert MonthlySpend(path, month="2026-06").spent() == 0.0


def test_committed_config_pricing_and_budget_parse() -> None:
    # The committed config must parse and declare a monthly budget (#511).
    import yaml

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / "config" / "local_models.yaml").read_text())
    # pricing parses (empty today — all providers are free tiers)
    assert load_pricing(cfg) == {}
    # a monthly cap is declared for the budget alarm
    assert int(cfg["monthly_budget_usd"]) >= 0
