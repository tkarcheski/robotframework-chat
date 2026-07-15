"""RFC-007 S4 (#220): McNemar harness-pair significance gate -- "is the difference real?"

Ports the exact-McNemar statistical honesty proven for *model* comparison in
rsi-loop (``finetune/gate.py``, ``mcnemar_from_pairs``) onto *harness*
comparison. Where S2 (:mod:`rfc.harness_comparison`, #218) writes
honestly-pairable per-run rows to the spine, this module answers the owner's
standing question over those rows: **is harness B actually better than harness
A, or is the gap luck?**

Ported faithfully from ``gate.py``:

  * the paired discordant split -- ``b`` = A passed / B failed (B lost the
    pair), ``c`` = A failed / B passed (B won the pair);
  * the exact McNemar p-value -- ``binomtest(c, b+c, 0.5, alternative="greater")``,
    reimplemented in stdlib :func:`math.comb` (identical values; core carries no
    scipy, and RFC-007's premise is "the smallest benchmark that discriminates",
    so a one-line exact binomial beats a heavy dependency);
  * the two-part "difference is real" gate -- ``delta_pass >= min_effect_pp AND
    p < alpha`` (defaults 5pp / 0.05, RFC-007 section 8).

Adapted -- honest deltas from the port, tracked on #220:

  * ``gate.py`` returns a **fake ``p = 1.0``** when there are no discordant pairs
    (``b + c == 0``). This gate instead emits an explicit ``insufficient_pairs``
    verdict with ``p_value = None`` -- "collect more pairs before claiming
    anything" (RFC-007 section 8), which #221's scoreboard renders as *tied*,
    never a fake non-result. The degenerate all-concordant case is honest, not
    silently "not significant at p=1".
  * emits a typed, frozen :class:`McNemarVerdict` (``as_dict()``-able) instead of
    a bare dict, so #221's scoreboard consumes the p-value/delta per harness pair
    per scenario as **data**, not printed prose (RFC-007 section 6.3, Gantt's
    note on #220).
  * carries the McNemar chi-square statistic ``(b - c)**2 / (b + c)`` for
    display; the *significance decision* still uses the exact-binomial p (the
    statistic is descriptive -- ``gate.py`` reports neither b/c nor a statistic,
    so this is additive display only, never the decision).
  * **Tier-A-only enforcement.** A pair is built ONLY from Tier-A rows that carry
    the gate-minted :class:`~rfc.opencode_config.VerifiedLocalModel` token
    (#278/#314). A Tier-B native run is **never** paired (the #273 lesson):
    pairing refuses with :class:`~rfc.opencode_config.ComparabilityError` before
    any statistic is computed. Both legs must further share one fixed local
    ``model_id`` -- Tier A means "same local model for every harness" (RFC-007
    section 5), so pairing two *different* local models would measure the model,
    not the harness. ``gate.py`` had no tiers (one model, by construction), so
    this enforcement is new here and load-bearing.

The pairing key is the STORED ``(battery_run_id, scenario_id, repeat_idx)`` the
spine records (#277), not fragile row order: a skipped repeat is a visible hole
that simply drops that pair, never a silently shifted comparison.

Deterministic twin: ``tests/test_harness_significance.py`` drives every branch
(known-answer McNemar cases, the all-concordant degenerate, insufficient/
underpowered honesty, and Tier-A/token enforcement) against hand-minted rows --
no models, no DB, no scipy.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass

from robot.api.deco import keyword  # type: ignore[import-untyped]

from rfc.harness_comparison import (
    TIER_A_FIXED_LOCAL,
    ComparisonReport,
    ComparisonRow,
)
from rfc.harness_models import METRIC_TASK_SUCCESS
from rfc.opencode_config import ComparabilityError, VerifiedLocalModel

# RFC-007 section 8 defaults, verbatim from the model gate: a difference is
# "real" only above a 5-percentage-point effect AND below a 0.05 exact p.
DEFAULT_ALPHA = 0.05
DEFAULT_MIN_EFFECT_PP = 5.0

# Honest verdict outcomes. Only REASON_REAL is "harness B is better"; every other
# reason is what #221's scoreboard renders as *tied*, never a faint-green
# "better" (RFC-007 section 10, the small-N over-claiming guard).
REASON_NO_PAIRS = "no_pairs"  # nothing paired under both harnesses
REASON_ALL_CONCORDANT = "all_concordant"  # every pair agreed -> no discordant signal
REASON_UNDERPOWERED = "underpowered"  # b+c too small to ever reach alpha
REASON_NOT_SIGNIFICANT = "not_significant"  # enough power in principle; p >= alpha
REASON_SIGNIFICANT_TRIVIAL = "significant_trivial"  # p < alpha but delta < min_effect
REASON_REAL = "real"  # p < alpha AND delta >= min_effect -> B genuinely better

# The reasons the scoreboard renders as "tied" (everything but a real win).
TIED_REASONS: frozenset[str] = frozenset(
    {
        REASON_NO_PAIRS,
        REASON_ALL_CONCORDANT,
        REASON_UNDERPOWERED,
        REASON_NOT_SIGNIFICANT,
        REASON_SIGNIFICANT_TRIVIAL,
    }
)


@dataclass(frozen=True)
class McNemarVerdict:
    """The verdict for one harness pair (pooled, or one scenario).

    Pure data: frozen and ``as_dict()``-able so #221's scoreboard consumes it
    directly (RFC-007 section 6.3). ``harness_b`` is the hypothesised *better*
    harness -- the exact-binomial p answers "is B better than A?" one-sidedly
    (``gate.py``'s ``alternative="greater"``); to test the other direction, swap
    the arguments. Direction is always recoverable from ``delta_pp`` (positive =
    B ahead) and the ``b``/``c`` split regardless.

    ``statistic`` and ``p_value`` are ``None`` -- never a fake number -- whenever
    ``insufficient_pairs`` is set (no pairs, or all pairs concordant).
    """

    harness_a: str
    harness_b: str
    scenario_id: str  # "" == pooled across every scenario in the pairing
    model_id: str  # the shared fixed local model both Tier-A legs ran ("" if no pairs)
    n_pairs: int
    n_concordant: int
    b: int  # A passed, B failed  (B lost the pair)
    c: int  # A failed, B passed  (B won the pair)
    n_discordant: int
    a_pass_rate: float  # percent
    b_pass_rate: float  # percent
    delta_pp: float  # b_pass_rate - a_pass_rate, in percentage points
    alpha: float
    min_effect_pp: float
    statistic: float | None  # McNemar chi-square (b-c)^2/(b+c); None if insufficient
    p_value: float | None  # exact one-sided binomial p; None if insufficient
    significant: bool  # p < alpha (statistical significance alone), sufficient pairs
    passes: bool  # RFC-007 s8 two-part gate: delta_pp >= min_effect_pp AND significant
    insufficient_pairs: bool  # no pairs, or all concordant -> no honest p to report
    underpowered: bool  # discordant pairs exist but too few to ever reach alpha
    reason: str

    @property
    def tied(self) -> bool:
        """True unless B is genuinely better -- how #221 renders the cell."""
        return not self.passes

    def as_dict(self) -> dict[str, object]:
        """Plain dict for the scoreboard / JSON (``p_value``/``statistic`` may be None)."""
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Ported statistics (stdlib exact binomial; no scipy).
# ---------------------------------------------------------------------------


def _exact_binom_greater_p(c: int, n: int) -> float:
    """``P(X >= c)`` for ``X ~ Binomial(n, 0.5)`` -- the exact one-sided McNemar p.

    Value-identical to ``scipy.stats.binomtest(c, n, 0.5, alternative="greater")``
    (verified on the known-answer cases in the twin). Ported from ``gate.py``'s
    ``binomtest(c, b + c, 0.5, alternative="greater")`` in stdlib so core keeps no
    scipy dependency. ``math.comb`` is exact-integer, so only the final division
    is floating point.
    """
    if n <= 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(c, n + 1))
    return tail / (2**n)


def mcnemar_from_pairs(
    pairs: Sequence[tuple[bool, bool]],
    *,
    alpha: float = DEFAULT_ALPHA,
    min_effect_pp: float = DEFAULT_MIN_EFFECT_PP,
    harness_a: str = "",
    harness_b: str = "",
    scenario_id: str = "",
    model_id: str = "",
) -> McNemarVerdict:
    """Exact McNemar over paired ``(a_passed, b_passed)`` binary outcomes.

    Faithful port of ``gate.py``'s ``mcnemar_from_pairs`` -- same discordant
    split, same exact-binomial one-sided p, same two-part gate -- with the honest
    ``insufficient_pairs`` adaptation replacing its fake ``p = 1.0`` when there
    are no discordant pairs.
    """
    n = len(pairs)
    if n == 0:
        return _insufficient(
            REASON_NO_PAIRS,
            harness_a=harness_a,
            harness_b=harness_b,
            scenario_id=scenario_id,
            model_id=model_id,
            alpha=alpha,
            min_effect_pp=min_effect_pp,
            n_pairs=0,
            a_pass_rate=0.0,
            b_pass_rate=0.0,
            b=0,
            c=0,
        )

    b = sum(1 for a_pass, b_pass in pairs if a_pass and not b_pass)
    c = sum(1 for a_pass, b_pass in pairs if (not a_pass) and b_pass)
    n_discordant = b + c
    a_pass_rate = sum(1 for a_pass, _ in pairs if a_pass) / n * 100.0
    b_pass_rate = sum(1 for _, b_pass in pairs if b_pass) / n * 100.0
    delta_pp = b_pass_rate - a_pass_rate

    if n_discordant == 0:
        # Every pair agreed (both passed or both failed): McNemar is 0/0. There is
        # no directional evidence, so the honest answer is "insufficient", NOT the
        # p=1.0 gate.py would emit here (the #220 adaptation).
        return _insufficient(
            REASON_ALL_CONCORDANT,
            harness_a=harness_a,
            harness_b=harness_b,
            scenario_id=scenario_id,
            model_id=model_id,
            alpha=alpha,
            min_effect_pp=min_effect_pp,
            n_pairs=n,
            a_pass_rate=a_pass_rate,
            b_pass_rate=b_pass_rate,
            b=b,
            c=c,
        )

    statistic = (b - c) ** 2 / n_discordant
    p_value = _exact_binom_greater_p(c, n_discordant)
    # Even a unanimous B-favouring split (c == n_discordant, b == 0) gives
    # p = 0.5**n_discordant; if that floor already exceeds alpha, no outcome at this
    # discordant count can reach significance -- "collect more pairs" (RFC-007 s8).
    underpowered = (0.5**n_discordant) > alpha
    significant = p_value < alpha
    passes = significant and delta_pp >= min_effect_pp

    if passes:
        reason = REASON_REAL
    elif significant:
        reason = REASON_SIGNIFICANT_TRIVIAL
    elif underpowered:
        reason = REASON_UNDERPOWERED
    else:
        reason = REASON_NOT_SIGNIFICANT

    return McNemarVerdict(
        harness_a=harness_a,
        harness_b=harness_b,
        scenario_id=scenario_id,
        model_id=model_id,
        n_pairs=n,
        n_concordant=n - n_discordant,
        b=b,
        c=c,
        n_discordant=n_discordant,
        a_pass_rate=a_pass_rate,
        b_pass_rate=b_pass_rate,
        delta_pp=delta_pp,
        alpha=alpha,
        min_effect_pp=min_effect_pp,
        statistic=statistic,
        p_value=p_value,
        significant=significant,
        passes=passes,
        insufficient_pairs=False,
        underpowered=underpowered,
        reason=reason,
    )


def _insufficient(
    reason: str,
    *,
    harness_a: str,
    harness_b: str,
    scenario_id: str,
    model_id: str,
    alpha: float,
    min_effect_pp: float,
    n_pairs: int,
    a_pass_rate: float,
    b_pass_rate: float,
    b: int,
    c: int,
) -> McNemarVerdict:
    """A verdict with no honest p to report: statistic/p_value are None, not faked."""
    return McNemarVerdict(
        harness_a=harness_a,
        harness_b=harness_b,
        scenario_id=scenario_id,
        model_id=model_id,
        n_pairs=n_pairs,
        n_concordant=n_pairs - (b + c),
        b=b,
        c=c,
        n_discordant=b + c,
        a_pass_rate=a_pass_rate,
        b_pass_rate=b_pass_rate,
        delta_pp=b_pass_rate - a_pass_rate,
        alpha=alpha,
        min_effect_pp=min_effect_pp,
        statistic=None,
        p_value=None,
        significant=False,
        passes=False,
        insufficient_pairs=True,
        underpowered=False,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Pairing over the recorded spine rows (Tier-A + token enforced).
# ---------------------------------------------------------------------------


def _row_passed(row: ComparisonRow) -> bool:
    """Binary McNemar input for a row: its ``task_success`` metric (RFC-007 6.1).

    ``task_success`` is 1.0 iff the scenario tests pass, no unexpected churn, and
    no timeout -- equivalently ``outcome == "success"``. It is the RFC-designated
    McNemar input (section 6.1). A paired row without it is malformed and refused
    loudly rather than silently scored as a failure.
    """
    if METRIC_TASK_SUCCESS not in row.metrics:
        raise ValueError(
            f"row {row.session_id!r} (harness {row.harness!r}, scenario "
            f"{row.scenario_id!r}) has no {METRIC_TASK_SUCCESS!r} metric -- cannot "
            "use it as a McNemar pass/fail outcome."
        )
    return row.metrics[METRIC_TASK_SUCCESS] >= 1.0


def _require_tier_a(row: ComparisonRow) -> None:
    """Refuse to pair any non-Tier-A / untokened row (#273/#278/#314).

    The #273 lesson: a Tier-B native run is descriptive-only and must never enter
    a head-to-head. Enforced structurally via the capability token rather than by
    convention -- a Tier-A row without the exact gate-minted
    :class:`VerifiedLocalModel` type is refused before any statistic is computed
    (belt-and-suspenders over :class:`ComparisonRow`'s own construction invariant,
    so this gate is self-defending even if handed hand-built rows).
    """
    if row.tier != TIER_A_FIXED_LOCAL:
        raise ComparabilityError(
            f"refusing to pair harness {row.harness!r}: its row is tier "
            f"{row.tier!r}, not Tier-A ({TIER_A_FIXED_LOCAL!r}). A Tier-B native "
            "run is descriptive-only and is never placed in a harness-vs-harness "
            "significance test (RFC-007 section 5, the #273 lesson)."
        )
    if type(row.verified_model) is not VerifiedLocalModel:
        raise ComparabilityError(
            f"refusing to pair harness {row.harness!r}: its Tier-A row carries no "
            "gate-minted VerifiedLocalModel token -- an unverified (remote / "
            "undeclared) model cannot be treated as a fixed-local comparison leg "
            "(#278/#314)."
        )


def _paired_outcomes(
    rows: Sequence[ComparisonRow], harness_a: str, harness_b: str
) -> tuple[list[tuple[str, bool, bool]], str]:
    """Pair two harnesses on the stored ``(battery_run_id, scenario_id, repeat_idx)``.

    Returns ``(triples, model_id)`` where each triple is
    ``(scenario_id, a_passed, b_passed)`` for every key present under BOTH
    harnesses, and ``model_id`` is the single fixed local model both legs ran.
    Enforces Tier-A + token on every consumed row, and that both legs share one
    ``model_id`` (Tier A = "same local model for every harness", RFC-007 s5).
    """
    if harness_a == harness_b:
        raise ValueError(
            f"cannot run a significance test of harness {harness_a!r} against "
            "itself -- pass two distinct harnesses."
        )

    a_by_key: dict[tuple[str, str, int], ComparisonRow] = {}
    b_by_key: dict[tuple[str, str, int], ComparisonRow] = {}
    model_ids: set[str] = set()

    for row in rows:
        if row.harness == harness_a:
            target = a_by_key
        elif row.harness == harness_b:
            target = b_by_key
        else:
            continue
        _require_tier_a(row)
        key = (row.battery_run_id, row.scenario_id, row.repeat_idx)
        if key in target:
            raise ValueError(
                f"duplicate spine row for harness {row.harness!r} at "
                f"battery_run_id={row.battery_run_id!r} scenario={row.scenario_id!r} "
                f"repeat={row.repeat_idx} -- each (harness, battery, scenario, "
                "repeat) must be a single run to pair honestly."
            )
        target[key] = row
        model_ids.add(row.model_id)

    if len(model_ids) > 1:
        raise ComparabilityError(
            f"refusing to pair harnesses {harness_a!r} and {harness_b!r} across "
            f"different local models {sorted(model_ids)} -- Tier A holds the model "
            "constant (RFC-007 section 5); a pairing over two models measures the "
            "model, not the harness."
        )

    model_id = next(iter(model_ids)) if model_ids else ""
    triples: list[tuple[str, bool, bool]] = []
    for key in sorted(a_by_key.keys() & b_by_key.keys()):
        _battery, scenario_id, _repeat = key
        triples.append(
            (scenario_id, _row_passed(a_by_key[key]), _row_passed(b_by_key[key]))
        )
    return triples, model_id


# ---------------------------------------------------------------------------
# Public gate surface (mirrors rfc.harness_comparison: dataclass out + keyword).
# ---------------------------------------------------------------------------


def _rows_of(
    source: ComparisonReport | Sequence[ComparisonRow],
) -> Sequence[ComparisonRow]:
    return source.rows if isinstance(source, ComparisonReport) else source


def mcnemar_gate(
    source: ComparisonReport | Sequence[ComparisonRow],
    harness_a: str,
    harness_b: str,
    *,
    alpha: float = DEFAULT_ALPHA,
    min_effect_pp: float = DEFAULT_MIN_EFFECT_PP,
) -> McNemarVerdict:
    """Pooled verdict: is ``harness_b`` better than ``harness_a`` across the battery?

    Consumes the recorded rows (a :class:`ComparisonReport` or any sequence of
    :class:`ComparisonRow`), pools every scenario into one exact-McNemar test, and
    returns a :class:`McNemarVerdict`. Tier-A + token enforced (see
    :func:`_require_tier_a`); an absent second Tier-A leg yields an honest
    ``insufficient_pairs`` verdict, never a crash.
    """
    triples, model_id = _paired_outcomes(_rows_of(source), harness_a, harness_b)
    pairs = [(a_pass, b_pass) for _, a_pass, b_pass in triples]
    return mcnemar_from_pairs(
        pairs,
        alpha=alpha,
        min_effect_pp=min_effect_pp,
        harness_a=harness_a,
        harness_b=harness_b,
        scenario_id="",
        model_id=model_id,
    )


def mcnemar_gate_by_scenario(
    source: ComparisonReport | Sequence[ComparisonRow],
    harness_a: str,
    harness_b: str,
    *,
    alpha: float = DEFAULT_ALPHA,
    min_effect_pp: float = DEFAULT_MIN_EFFECT_PP,
) -> dict[str, McNemarVerdict]:
    """Per-scenario verdicts -- the "p-value + delta per harness pair per scenario"
    overlay #221's scoreboard renders (RFC-007 section 6.3).

    Returns a scenario_id -> :class:`McNemarVerdict` map (sorted). Each scenario
    is tested independently, so an intrinsically hard scenario does not inflate
    the variance of an easy one's difference (RFC-007 section 8, the paired
    design).
    """
    triples, model_id = _paired_outcomes(_rows_of(source), harness_a, harness_b)
    by_scenario: dict[str, list[tuple[bool, bool]]] = {}
    for scenario_id, a_pass, b_pass in triples:
        by_scenario.setdefault(scenario_id, []).append((a_pass, b_pass))
    return {
        scenario_id: mcnemar_from_pairs(
            scenario_pairs,
            alpha=alpha,
            min_effect_pp=min_effect_pp,
            harness_a=harness_a,
            harness_b=harness_b,
            scenario_id=scenario_id,
            model_id=model_id,
        )
        for scenario_id, scenario_pairs in sorted(by_scenario.items())
    }


class HarnessSignificanceKeywords:
    """Robot keyword surface for RFC-007 S4 (#220), sibling to
    :class:`rfc.harness_comparison.HarnessComparisonKeywords`.

    Chains off ``Run Harness Comparison Battery`` (S2): take the returned
    :class:`ComparisonReport` and ask whether one harness is really better than
    another. The deterministic coverage is ``tests/test_harness_significance.py``;
    this surface is for the gated live matrix.
    """

    ROBOT_LIBRARY_SCOPE = "SUITE"

    @keyword("Mcnemar Verdict For Harness Pair")
    def mcnemar_verdict_for_harness_pair(
        self,
        report: ComparisonReport | Sequence[ComparisonRow],
        harness_a: str,
        harness_b: str,
        alpha: float = DEFAULT_ALPHA,
        min_effect_pp: float = DEFAULT_MIN_EFFECT_PP,
    ) -> McNemarVerdict:
        """Pooled McNemar verdict for ``harness_b`` vs ``harness_a`` over ``report``."""
        return mcnemar_gate(
            report,
            harness_a,
            harness_b,
            alpha=float(alpha),
            min_effect_pp=float(min_effect_pp),
        )

    @keyword("Mcnemar Verdict Should Be Insufficient")
    def mcnemar_verdict_should_be_insufficient(self, verdict: McNemarVerdict) -> None:
        """Assert the verdict is an honest insufficient-pairs non-result (no fake p)."""
        if not verdict.insufficient_pairs:
            raise AssertionError(
                "expected an insufficient-pairs verdict, got "
                f"reason={verdict.reason!r} p_value={verdict.p_value!r} "
                f"n_pairs={verdict.n_pairs}"
            )

    @keyword("Mcnemar Verdict Should Show Real Difference")
    def mcnemar_verdict_should_show_real_difference(
        self, verdict: McNemarVerdict
    ) -> None:
        """Assert the two-part gate passed: B is significantly and non-trivially better."""
        if not verdict.passes:
            raise AssertionError(
                "expected a real (significant + non-trivial) difference, got "
                f"reason={verdict.reason!r} p_value={verdict.p_value!r} "
                f"delta_pp={verdict.delta_pp!r}"
            )
