"""Deterministic twin for RFC-007 S4 -- the McNemar harness-pair gate (#220).

Drives every branch against hand-minted rows and hand-computed McNemar cases:
no models, no DB, no scipy. The known-answer p-values below are computed by hand
from the exact binomial on the discordant pairs (``P(X >= c)`` for
``X ~ Binomial(b + c, 0.5)``) -- the same value ``gate.py``'s
``binomtest(c, b + c, 0.5, alternative="greater")`` returns.
"""

from __future__ import annotations

import json
import types

import pytest

from rfc.harness_comparison import (
    TIER_A_FIXED_LOCAL,
    TIER_B_NATIVE,
    ComparisonReport,
    ComparisonRow,
)
from rfc.harness_models import METRIC_TASK_SUCCESS
from rfc.harness_significance import (
    REASON_ALL_CONCORDANT,
    REASON_NO_PAIRS,
    REASON_NOT_SIGNIFICANT,
    REASON_REAL,
    REASON_SIGNIFICANT_TRIVIAL,
    REASON_UNDERPOWERED,
    HarnessSignificanceKeywords,
    McNemarVerdict,
    _exact_binom_greater_p,
    _require_tier_a,
    mcnemar_from_pairs,
    mcnemar_gate,
    mcnemar_gate_by_scenario,
)
from rfc.opencode_config import ComparabilityError, assert_model_resolves_local

# A minimal declared-local opencode config, so the tests can mint genuine
# gate-verified VerifiedLocalModel tokens for Tier-A rows (mirrors the pattern in
# test_harness_comparison.py). Two models are declared so the "two Tier-A legs on
# DIFFERENT local models" comparability case can be built honestly.
_LOCAL_CFG = {
    "model": "ollama/model-x",
    "provider": {
        "ollama": {
            "options": {"baseURL": "http://localhost:11434/v1"},
            "models": {"model-x": {}, "model-y": {}},
        }
    },
}


def _token(model_ref: str = "ollama/model-x"):
    return assert_model_resolves_local(model_ref, _LOCAL_CFG, source="test")


def _row(
    harness: str,
    scenario_id: str,
    repeat_idx: int,
    passed: bool,
    *,
    tier: str = TIER_A_FIXED_LOCAL,
    model_id: str = "ollama/model-x",
    battery_run_id: str = "batt-1",
) -> ComparisonRow:
    """Build one recorded spine row. Tier-A rows carry a real gate-minted token."""
    verified = _token(model_id) if tier == TIER_A_FIXED_LOCAL else None
    return ComparisonRow(
        scenario_id=scenario_id,
        battery_run_id=battery_run_id,
        harness=harness,
        model_id=model_id,
        tier=tier,
        repeat_idx=repeat_idx,
        session_id=f"{harness}-{scenario_id}-{repeat_idx}-{battery_run_id}",
        outcome="success" if passed else "failed",
        metrics={METRIC_TASK_SUCCESS: 1.0 if passed else 0.0},
        verified_model=verified,
    )


def _discordant_b_wins(
    harness_a: str, harness_b: str, scenario_id: str, n: int, *, battery="batt-1"
):
    """``n`` paired repeats where B passes and A fails (B wins every discordant)."""
    rows = []
    for i in range(n):
        rows.append(
            _row(harness_a, scenario_id, i, passed=False, battery_run_id=battery)
        )
        rows.append(
            _row(harness_b, scenario_id, i, passed=True, battery_run_id=battery)
        )
    return rows


# ---------------------------------------------------------------------------
# Ported exact-binomial math -- value-identical to scipy binomtest greater.
# ---------------------------------------------------------------------------


class TestExactBinomial:
    @pytest.mark.parametrize(
        "c,n,expected",
        [
            (5, 5, 1 / 32),  # unanimous B, 5 discordant
            (0, 5, 1.0),  # P(X >= 0) == 1
            (4, 4, 1 / 16),  # 0.0625
            (9, 10, 11 / 1024),  # comb(10,9)+comb(10,10) = 11
            (8, 8, 1 / 256),  # unanimous B, 8 discordant
            (5, 10, 638 / 1024),  # even split, sum k=5..10
            (10, 10, 1 / 1024),
            (4, 5, 3 / 16),  # b=1, c=4: asymmetric small tail P(X>=4), n=5 -> 6/32
            (1, 1, 1 / 2),  # b=0, c=1: single discordant pair -> P(X>=1), n=1
            # b=10, c=25: larger asymmetric tail, hand-computed as
            # sum(comb(35, k) for k in 25..35) / 2**35 = 71613631 / 8589934592.
            (25, 35, 71613631 / 8589934592),
        ],
    )
    def test_known_tail_probabilities(self, c, n, expected) -> None:
        assert _exact_binom_greater_p(c, n) == pytest.approx(expected)

    def test_zero_discordant_is_one(self) -> None:
        assert _exact_binom_greater_p(0, 0) == 1.0


# ---------------------------------------------------------------------------
# Known-answer verdicts over raw pairs (the ported mcnemar_from_pairs).
# ---------------------------------------------------------------------------


class TestMcNemarFromPairs:
    def test_real_difference_unanimous_five(self) -> None:
        # b=0, c=5: exact p = 1/32 = 0.03125 < 0.05, delta = 100pp >= 5 -> real.
        verdict = mcnemar_from_pairs([(False, True)] * 5)
        assert (verdict.b, verdict.c, verdict.n_discordant) == (0, 5, 5)
        assert verdict.statistic == pytest.approx(5.0)  # (0-5)^2/5
        assert verdict.p_value == pytest.approx(1 / 32)
        assert verdict.significant is True
        assert verdict.passes is True
        assert verdict.tied is False
        assert verdict.reason == REASON_REAL
        assert verdict.delta_pp == pytest.approx(100.0)
        assert verdict.underpowered is False

    def test_underpowered_four_discordant_cannot_reach_alpha(self) -> None:
        # b=0, c=4: even a unanimous split gives p = 1/16 = 0.0625 > 0.05. No
        # outcome at 4 discordant pairs can be significant -> collect more (tied).
        verdict = mcnemar_from_pairs([(False, True)] * 4)
        assert verdict.p_value == pytest.approx(1 / 16)
        assert verdict.underpowered is True
        assert verdict.significant is False
        assert verdict.passes is False
        assert verdict.tied is True
        assert verdict.reason == REASON_UNDERPOWERED

    def test_all_concordant_is_insufficient_not_fake_p1(self) -> None:
        # gate.py returns a fake p=1.0 here; we return an honest insufficient
        # verdict with p_value=None (the #220 adaptation).
        verdict = mcnemar_from_pairs([(True, True), (True, True), (False, False)])
        assert verdict.insufficient_pairs is True
        assert verdict.reason == REASON_ALL_CONCORDANT
        assert verdict.p_value is None
        assert verdict.statistic is None
        assert verdict.n_discordant == 0
        assert verdict.n_pairs == 3
        assert verdict.n_concordant == 3
        assert verdict.significant is False
        assert verdict.passes is False
        assert verdict.a_pass_rate == pytest.approx(2 / 3 * 100)
        assert verdict.b_pass_rate == pytest.approx(2 / 3 * 100)
        assert verdict.delta_pp == pytest.approx(0.0)

    def test_no_pairs_is_insufficient(self) -> None:
        verdict = mcnemar_from_pairs([])
        assert verdict.insufficient_pairs is True
        assert verdict.reason == REASON_NO_PAIRS
        assert verdict.p_value is None
        assert verdict.n_pairs == 0

    def test_significant_but_trivial_effect_is_tied(self) -> None:
        # 8 discordant B-wins (p = 1/256 << 0.05) but only a 4pp pass-rate lift
        # because 192 pairs both pass -> below the 5pp floor -> tied, not "better".
        pairs = [(False, True)] * 8 + [(True, True)] * 192
        verdict = mcnemar_from_pairs(pairs)
        assert verdict.p_value == pytest.approx(1 / 256)
        assert verdict.significant is True
        assert verdict.delta_pp == pytest.approx(4.0)
        assert verdict.passes is False  # significant but trivial
        assert verdict.tied is True
        assert verdict.reason == REASON_SIGNIFICANT_TRIVIAL

    def test_larger_asymmetric_split_is_a_real_difference(self) -> None:
        # b=10, c=25 (35 discordant, no concordant). Hand-computed exact one-sided
        # p = sum(comb(35, k), k=25..35) / 2**35 = 71613631 / 8589934592
        # ~ 0.008337 < 0.05; delta = (c - b) / n = 15/35 -> ~42.86pp >= 5, so the
        # two-part gate passes. Locks the asymmetric-larger tail the port must match.
        pairs = [(True, False)] * 10 + [(False, True)] * 25
        verdict = mcnemar_from_pairs(pairs)
        assert (verdict.b, verdict.c, verdict.n_discordant) == (10, 25, 35)
        assert verdict.n_concordant == 0
        assert verdict.p_value == pytest.approx(71613631 / 8589934592)
        assert verdict.p_value == pytest.approx(0.008336923900060356)
        assert verdict.statistic == pytest.approx(225 / 35)  # (10 - 25)^2 / 35
        assert verdict.delta_pp == pytest.approx(15 / 35 * 100)
        assert verdict.underpowered is False
        assert verdict.significant is True
        assert verdict.passes is True
        assert verdict.reason == REASON_REAL

    def test_single_discordant_pair_is_underpowered(self) -> None:
        # b=0, c=1: the smallest non-empty discordant count. Even this unanimous
        # B-win has p = 0.5 (one coin flip), and 0.5**1 > 0.05, so no single
        # discordant pair can EVER reach alpha -> underpowered, never significant.
        # This is the lower boundary of the "min b+c to reach 0.05 is 5" claim.
        verdict = mcnemar_from_pairs([(False, True)])
        assert (verdict.b, verdict.c, verdict.n_discordant) == (0, 1, 1)
        assert verdict.p_value == pytest.approx(0.5)
        assert verdict.underpowered is True
        assert verdict.significant is False
        assert verdict.passes is False
        assert verdict.reason == REASON_UNDERPOWERED
        assert verdict.delta_pp == pytest.approx(100.0)

    def test_even_split_not_significant(self) -> None:
        # b=c=5, n_discordant=10: p = 638/1024 ~ 0.62. Powered but no difference.
        pairs = [(True, False)] * 5 + [(False, True)] * 5
        verdict = mcnemar_from_pairs(pairs)
        assert (verdict.b, verdict.c) == (5, 5)
        assert verdict.statistic == pytest.approx(0.0)
        assert verdict.p_value == pytest.approx(638 / 1024)
        assert verdict.underpowered is False
        assert verdict.significant is False
        assert verdict.reason == REASON_NOT_SIGNIFICANT

    def test_one_sided_direction_a_better_is_not_significant(self) -> None:
        # B loses every discordant pair (b=5, c=0): "is B better than A?" is a firm
        # no (p=1.0). Swapping the pair order tests the reverse and IS significant.
        b_worse = mcnemar_from_pairs([(True, False)] * 5)
        assert b_worse.p_value == pytest.approx(1.0)
        assert b_worse.passes is False
        assert b_worse.delta_pp == pytest.approx(-100.0)
        swapped = mcnemar_from_pairs([(False, True)] * 5)
        assert swapped.passes is True

    def test_min_effect_and_alpha_are_configurable(self) -> None:
        pairs = [(False, True)] * 4
        # Relaxing alpha to 0.1 makes the 4-discordant unanimous case significant.
        loose = mcnemar_from_pairs(pairs, alpha=0.1)
        assert loose.significant is True
        assert loose.passes is True
        assert loose.underpowered is False


# ---------------------------------------------------------------------------
# Tier-A + capability-token enforcement (the #273 lesson).
# ---------------------------------------------------------------------------


class TestTierEnforcement:
    def test_refuses_to_pair_a_tier_b_native_run(self) -> None:
        rows = [
            _row("opencode", "s1", 0, passed=True),
            _row("claude-code", "s1", 0, passed=False, tier=TIER_B_NATIVE, model_id=""),
        ]
        with pytest.raises(ComparabilityError, match="Tier-B|tier 'B'|#273"):
            mcnemar_gate(rows, "opencode", "claude-code")

    def test_require_tier_a_rejects_tier_a_row_missing_token(self) -> None:
        # A ComparisonRow cannot itself be built Tier-A without a token, so the
        # belt-and-suspenders token check is exercised via a forged stand-in --
        # exactly the shape a future runner building rows by hand would trip.
        forged = types.SimpleNamespace(
            tier=TIER_A_FIXED_LOCAL, verified_model=None, harness="opencode"
        )
        with pytest.raises(ComparabilityError, match="token"):
            _require_tier_a(forged)  # type: ignore[arg-type]

    def test_require_tier_a_rejects_wrong_token_type(self) -> None:
        forged = types.SimpleNamespace(
            tier=TIER_A_FIXED_LOCAL,
            verified_model=object(),
            harness="opencode",
        )
        with pytest.raises(ComparabilityError, match="token"):
            _require_tier_a(forged)  # type: ignore[arg-type]

    def test_refuses_two_tier_a_legs_on_different_models(self) -> None:
        rows = [
            _row("opencode", "s1", 0, passed=False, model_id="ollama/model-x"),
            _row("codex", "s1", 0, passed=True, model_id="ollama/model-y"),
        ]
        with pytest.raises(ComparabilityError, match="different local models"):
            mcnemar_gate(rows, "opencode", "codex")


# ---------------------------------------------------------------------------
# Pairing over recorded rows on the stored (battery, scenario, repeat) key.
# ---------------------------------------------------------------------------


class TestPairingOverRows:
    def test_second_tier_a_leg_pairs_and_finds_a_real_difference(self) -> None:
        # opencode (A) fails, codex (B) passes, across 5 paired repeats.
        rows = _discordant_b_wins("opencode", "codex", "tier4_bug_fix", 5)
        verdict = mcnemar_gate(rows, "opencode", "codex")
        assert verdict.harness_a == "opencode"
        assert verdict.harness_b == "codex"
        assert verdict.model_id == "ollama/model-x"
        assert verdict.n_pairs == 5
        assert verdict.passes is True
        assert verdict.reason == REASON_REAL

    def test_absent_second_leg_is_honest_insufficient(self) -> None:
        # Only opencode recorded (today's reality): codex has no rows -> no pairs.
        rows = [_row("opencode", "s1", i, passed=True) for i in range(5)]
        verdict = mcnemar_gate(rows, "opencode", "codex")
        assert verdict.insufficient_pairs is True
        assert verdict.reason == REASON_NO_PAIRS
        assert verdict.p_value is None

    def test_pairs_only_keys_present_under_both_harnesses(self) -> None:
        # opencode has repeats 0,1,2; codex has only 0,1 (a skipped repeat hole).
        rows = [
            _row("opencode", "s1", 0, passed=False),
            _row("opencode", "s1", 1, passed=False),
            _row("opencode", "s1", 2, passed=False),
            _row("codex", "s1", 0, passed=True),
            _row("codex", "s1", 1, passed=True),
        ]
        verdict = mcnemar_gate(rows, "opencode", "codex")
        assert verdict.n_pairs == 2  # repeat 2 dropped: no codex row to pair it

    def test_pooling_across_scenarios_gains_power(self) -> None:
        rows = _discordant_b_wins("opencode", "codex", "s1", 3) + _discordant_b_wins(
            "opencode", "codex", "s2", 2
        )
        pooled = mcnemar_gate(rows, "opencode", "codex")
        assert pooled.n_pairs == 5
        assert pooled.n_discordant == 5
        assert pooled.significant is True  # 5 discordant -> p = 1/32

        by_scenario = mcnemar_gate_by_scenario(rows, "opencode", "codex")
        assert set(by_scenario) == {"s1", "s2"}
        # Each scenario alone is underpowered (3 and 2 discordant < 5).
        assert by_scenario["s1"].underpowered is True
        assert by_scenario["s2"].underpowered is True
        assert by_scenario["s1"].scenario_id == "s1"

    def test_swapping_harness_order_flips_direction(self) -> None:
        # Direction is carried by argument order: (A, B) asks "is B better than A?".
        # opencode fails / codex passes across 5 repeats. Under (A=opencode,
        # B=codex), B wins every discordant pair; swapping the arguments makes
        # B=opencode the loser -- b and c swap and delta flips sign coherently, so
        # the one-sided verdict flips too. Exercises direction through the full
        # pairing path, not just raw pairs.
        rows = _discordant_b_wins("opencode", "codex", "s1", 5)
        forward = mcnemar_gate(rows, "opencode", "codex")
        reverse = mcnemar_gate(rows, "codex", "opencode")
        assert (forward.b, forward.c) == (0, 5)
        assert (reverse.b, reverse.c) == (5, 0)  # b and c swap on argument swap
        assert forward.delta_pp == pytest.approx(-reverse.delta_pp)  # sign flips
        assert forward.passes is True
        assert reverse.passes is False
        assert reverse.p_value == pytest.approx(1.0)  # P(X>=0), n=5

    def test_ragged_repeats_do_not_leak_into_pass_rates(self) -> None:
        # opencode ran repeats 0,1,2; codex ran only 0,1. The unpaired opencode
        # repeat-2 (a PASS) must NOT leak into a_pass_rate -- rates are computed
        # over the PAIRED set only, so a skipped repeat drops that pair cleanly and
        # never shifts the surviving comparison (the #277 "no silent shift" claim,
        # made numeric: were the dropped PASS leaking, a_pass_rate would read 33%).
        rows = [
            _row("opencode", "s1", 0, passed=False),
            _row("opencode", "s1", 1, passed=False),
            _row("opencode", "s1", 2, passed=True),  # unpaired: no codex repeat 2
            _row("codex", "s1", 0, passed=True),
            _row("codex", "s1", 1, passed=True),
        ]
        verdict = mcnemar_gate(rows, "opencode", "codex")
        assert verdict.n_pairs == 2
        assert verdict.a_pass_rate == pytest.approx(0.0)
        assert verdict.b_pass_rate == pytest.approx(100.0)
        assert (verdict.b, verdict.c) == (0, 2)

    def test_pairs_do_not_cross_battery_runs(self) -> None:
        # Same scenario/repeat in two different batteries must not pair together.
        rows = [
            _row("opencode", "s1", 0, passed=False, battery_run_id="A"),
            _row("codex", "s1", 0, passed=True, battery_run_id="B"),
        ]
        verdict = mcnemar_gate(rows, "opencode", "codex")
        assert verdict.insufficient_pairs is True  # keys differ by battery_run_id

    def test_duplicate_row_for_same_key_raises(self) -> None:
        rows = [
            _row("opencode", "s1", 0, passed=True),
            _row("opencode", "s1", 0, passed=False),
            _row("codex", "s1", 0, passed=True),
        ]
        with pytest.raises(ValueError, match="duplicate spine row"):
            mcnemar_gate(rows, "opencode", "codex")

    def test_self_comparison_raises(self) -> None:
        rows = [_row("opencode", "s1", 0, passed=True)]
        with pytest.raises(ValueError, match="itself"):
            mcnemar_gate(rows, "opencode", "opencode")

    def test_missing_task_success_metric_raises(self) -> None:
        good = _row("opencode", "s1", 0, passed=True)
        bad = ComparisonRow(
            scenario_id="s1",
            battery_run_id="batt-1",
            harness="codex",
            model_id="ollama/model-x",
            tier=TIER_A_FIXED_LOCAL,
            repeat_idx=0,
            session_id="codex-nometric",
            outcome="success",
            metrics={},  # no task_success recorded
            verified_model=_token(),
        )
        with pytest.raises(ValueError, match="task_success"):
            mcnemar_gate([good, bad], "opencode", "codex")

    def test_accepts_a_comparison_report(self) -> None:
        rows = _discordant_b_wins("opencode", "codex", "s1", 5)
        report = ComparisonReport(battery_run_id="batt-1", rows=tuple(rows))
        verdict = mcnemar_gate(report, "opencode", "codex")
        assert verdict.passes is True


# ---------------------------------------------------------------------------
# Data surface + Robot keyword surface.
# ---------------------------------------------------------------------------


class TestSurface:
    def test_verdict_as_dict_is_json_safe_with_none_pvalue(self) -> None:
        verdict = mcnemar_from_pairs([])
        payload = verdict.as_dict()
        assert payload["p_value"] is None
        assert payload["insufficient_pairs"] is True
        json.dumps(payload)  # must not raise -- scoreboard consumes it as data

    def test_verdict_as_dict_round_trips_a_real_result(self) -> None:
        verdict = mcnemar_from_pairs([(False, True)] * 5)
        payload = verdict.as_dict()
        assert payload["reason"] == REASON_REAL
        assert payload["p_value"] == pytest.approx(1 / 32)
        assert payload["statistic"] == pytest.approx(5.0)

    def test_keyword_pair_and_insufficient_assertion(self) -> None:
        kw = HarnessSignificanceKeywords()
        rows = [_row("opencode", "s1", i, passed=True) for i in range(3)]
        report = ComparisonReport(battery_run_id="batt-1", rows=tuple(rows))
        verdict = kw.mcnemar_verdict_for_harness_pair(report, "opencode", "codex")
        assert isinstance(verdict, McNemarVerdict)
        # opencode-only report -> insufficient; the assertion keyword passes.
        kw.mcnemar_verdict_should_be_insufficient(verdict)
        with pytest.raises(AssertionError):
            kw.mcnemar_verdict_should_show_real_difference(verdict)

    def test_keyword_real_difference_assertion(self) -> None:
        kw = HarnessSignificanceKeywords()
        rows = _discordant_b_wins("opencode", "codex", "s1", 5)
        report = ComparisonReport(battery_run_id="batt-1", rows=tuple(rows))
        verdict = kw.mcnemar_verdict_for_harness_pair(report, "opencode", "codex")
        kw.mcnemar_verdict_should_show_real_difference(verdict)
        with pytest.raises(AssertionError):
            kw.mcnemar_verdict_should_be_insufficient(verdict)
