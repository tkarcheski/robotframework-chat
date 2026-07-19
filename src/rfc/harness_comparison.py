"""RFC-007 S2 (#218): harness comparison mode over the tier:4 sandbox battery.

Where ``harness_matrix.robot`` runs ONE trivial task under each harness and
asserts the outcomes are *identical* (conformance, PR #212), this module runs
the discriminating tier:4 sandbox battery under each *available* harness,
``N`` paired repeats each, and *records* per-run metrics on the DB spine
instead of asserting equality. The McNemar significance gate over the pairs is
S4/#220 -- this module's job is only to write honestly-pairable rows.

What is honestly comparable today (RFC-007 section 5, the comparability
contract):

* **Tier A -- fixed local model.** ``opencode`` is pinned to the repo
  ``opencode.json`` default (a local Ollama model, no external egress -- the
  #191/#226 gate, hard-blocked below, not assumed). This is the only tier that
  holds the model constant for free, so it is the only tier a harness-vs-harness
  claim may live in. In the currently-available harness set it has exactly ONE
  member (opencode): ``codex`` is absent (it would join Tier A when installed)
  and ``claude-code`` cannot pin a local model (RFC-008). So the honest cross-
  harness head-to-head is *not available yet* -- it unlocks when a second
  fixed-local harness arrives. Until then Tier A yields within-harness
  reliability (opencode across scenarios x repeats) and correctly-paired rows
  ready for the second leg.
* **Tier B -- native model.** ``claude-code`` runs at its native frontier model.
  It is recorded and TAGGED as its own cost tier (``tier="B"``, a distinct
  ``model_id``), never subtracted from a Tier-A local number. The scoreboard
  (S5) must never place a Tier-A and a Tier-B cell in the same comparison.

The runner is shaped for N harnesses: add a second Tier-A leg and it pairs
automatically by ``(scenario_id, repeat_idx)``.

Deterministic twin: ``tests/test_harness_comparison.py`` drives the whole
metric-writing path against hermetic sqlite with an injected sandbox invoker
(no models, no Docker, no tokens).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from robot.api import logger
from robot.api.deco import keyword  # type: ignore[import-untyped]

from rfc import __version__
from rfc.agent_run import AgentRun
from rfc.agent_sandbox import (
    DEFAULT_SANDBOX_SCENARIOS_ROOT,
    AgentSandbox,
    SandboxResult,
    SandboxScenario,
    load_sandbox_scenario,
)
from rfc.agent_verifiers import (
    VerificationFailure,
    assert_no_commit_while_tests_red,
    assert_questions_are_multiple_choice,
)
from rfc.exceptions import HarnessNotAvailableError, LiveHarnessNotRoutedError
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import (
    METRIC_CHURN_RATIO,
    METRIC_LATENCY_MS,
    METRIC_PROCESS_VIOLATIONS,
    METRIC_SANDBOX_EXEC_OVERHEAD_MS,
    METRIC_TASK_SUCCESS,
    METRIC_TOKENS_IN,
    METRIC_TOKENS_OUT,
    AgenticHarness,
    AgenticMetric,
)
from rfc.opencode_config import (
    _DEFAULT_OPENCODE_CONFIG,
    ComparabilityError,
    VerifiedLocalModel,
    assert_model_resolves_local,
    gate_config,
    load_opencode_config,
)

# Re-exported so existing callers/tests keep importing the gate from here even
# though it now lives in the config-loader layer (#278).
from rfc.opencode_config import assert_opencode_comparable as assert_opencode_comparable

# RFC-007 section 8: start at N=5 paired repeats per (harness, scenario).
DEFAULT_REPEATS = 5

# The two quality-barred sandbox scenarios (#227/#245) the Wave-3 cut runs.
DEFAULT_BATTERY_SCENARIOS: tuple[str, ...] = (
    "tier4_bug_fix",
    "tier4_regression_guard",
)

# Cost tiers (RFC-007 section 4.3 / section 5). Only Tier-A legs -- every one
# pinned to the SAME local model -- are honestly comparable head-to-head.
TIER_A_FIXED_LOCAL = "A"  # opencode (+ codex when installed): pinned local Ollama
TIER_B_NATIVE = "B"  # claude-code: native frontier model, descriptive only

# The sandbox battery verifies with ``python -m unittest``, so the
# commit-while-red process gate tracks the ``unittest`` needle.
_SANDBOX_TEST_NEEDLE = "unittest"


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


@dataclass(frozen=True)
class HarnessLeg:
    """One harness in the comparison, tagged with its cost tier.

    ``model`` overrides the harness's default; ``""`` keeps the config default
    (for opencode, the pinned local model from ``opencode.json``).
    """

    harness: str  # a rfc.harness_cli.TOOLS taxonomy name
    model: str = ""
    tier: str = TIER_A_FIXED_LOCAL


@dataclass(frozen=True)
class ComparisonRow:
    """One (scenario, harness, repeat) result, as written to the spine."""

    scenario_id: str
    battery_run_id: str
    harness: str
    model_id: str
    tier: str
    repeat_idx: int
    session_id: str
    outcome: str
    metrics: dict[str, float]
    # #278: the gate-minted token proving ``model_id`` resolves to a declared-local
    # provider. Required for Tier A (see the invariant below); ``None`` for Tier B,
    # whose native model is descriptive only.
    verified_model: VerifiedLocalModel | None = None
    # #381: per-code-exec-call broker overhead samples (ms), carried up from the
    # run's :class:`~rfc.agent_sandbox.SandboxResult`. Populates the Tier-A cost
    # tier -- an honest Tier-A row proves not just task-success but WHAT the
    # container routing cost (docker-exec transport + marshalling per tool call).
    # Empty for a run whose code-exec never routed through the broker.
    sandbox_exec_overhead_ms: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        # Structural invariant (#273 + #278), not convention: a Tier-A ("fixed
        # local model") row must be backed by a gate-minted VerifiedLocalModel
        # TOKEN -- not merely a non-empty model_id string. Enforced at row
        # construction so EVERY leg -- not just opencode, and any FUTURE runner
        # building rows directly -- hits it. Because the comparability gate
        # (rfc.opencode_config) is the only intended minter of a
        # VerifiedLocalModel, a runner that omits the gate cannot build a Tier-A
        # row for an unverified (remote / undeclared) model: accidental omission
        # fails closed, so such a row is never persisted or paired. (#314
        # hardening: the row accepts only the EXACT VerifiedLocalModel type --
        # a duck-typed fake or a __post_init__-overriding subclass fails closed
        # at runtime, mypy-independent -- and the mint key is closure-bound in
        # rfc.opencode_config, not importable. The two forge paths that remain,
        # object.__new__ fabrication and closure-cell introspection, are
        # deliberate, review-visible acts the #314 design ruling left to review
        # + dual sign-off rather than an impossible in-process absolute.) A
        # harness that cannot pin the local model belongs in Tier B (RFC-007
        # section 5 / RFC-008).
        if self.tier != TIER_A_FIXED_LOCAL:
            return
        if self.verified_model is None:
            raise ComparabilityError(
                f"Tier-A row for harness {self.harness!r} (scenario "
                f"{self.scenario_id!r}) has no gate-verified local model -- a "
                "Tier-A (fixed-local) row must carry the VerifiedLocalModel token "
                "minted by the comparability gate (#273/#278); a harness that "
                "cannot pin the local model belongs in Tier B (RFC-007 section 5). "
                "Refusing to persist an unverified Tier-A row."
            )
        if type(self.verified_model) is not VerifiedLocalModel:
            raise ComparabilityError(
                f"Tier-A row for harness {self.harness!r} (scenario "
                f"{self.scenario_id!r}) carries a verified_model of type "
                f"{type(self.verified_model).__name__!r}, not the exact "
                "VerifiedLocalModel token type -- a duck-typed stand-in or a "
                "subclass overriding __post_init__ is not gate verification "
                "(#314). Refusing to persist the row."
            )
        if self.verified_model.model_id != self.model_id:
            raise ComparabilityError(
                f"Tier-A row for harness {self.harness!r} records model_id "
                f"{self.model_id!r} but its verification token attests "
                f"{self.verified_model.model_id!r} -- the recorded model must be "
                "exactly the gate-verified one, so a row cannot carry a token for a "
                "different model than it names (#278)."
            )

    @property
    def verified_local(self) -> bool:
        """The durable local-resolution verdict this row persists to the spine (#350).

        True iff the row carries the EXACT gate-minted ``VerifiedLocalModel`` token
        -- the same ``type(...) is VerifiedLocalModel`` predicate ``__post_init__``
        and the S4 pairing gate enforce, so this is the write-time invariant's own
        question ("did the model actually resolve local?"), not a re-derivation.
        Because ``__post_init__`` refuses to construct a Tier-A row without that
        token, this is True for exactly the rows the comparability gate admits as
        fixed-local. FAIL-CLOSED: a Tier-B row, an untokened row, or any duck-typed
        / subclassed stand-in is False and lands Tier B in the scoreboard view. The
        runner persists ``int(row.verified_local)`` onto ``agentic_harnesses`` so
        the view reads the token's verdict, never a tool_name name-coincidence.
        """
        return type(self.verified_model) is VerifiedLocalModel


@dataclass(frozen=True)
class ComparisonReport:
    """The rows written by one battery invocation, plus skipped legs."""

    battery_run_id: str
    rows: tuple[ComparisonRow, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()  # (harness, reason)


# ---------------------------------------------------------------------------
# Pure metric derivation from a SandboxResult (RFC-007 section 6.1). Only the
# reserved keys honestly capturable today; each is a named scoreboard consumer.
# ---------------------------------------------------------------------------


def compute_task_success(result: SandboxResult) -> float:
    """1.0 iff tests pass, no unexpected churn, and no harness timeout.

    "Negative case not triggered" (RFC-007 6.1) collapses, for a reference run,
    to "no churn outside allowed_paths". A timeout (#251) is never a success.
    """
    ok = (
        result.tests_passed and not result.has_unexpected_churn and not result.timed_out
    )
    return 1.0 if ok else 0.0


def compute_churn_ratio(result: SandboxResult, allowed_path_count: int) -> float:
    """Path-granularity edit-economy proxy (RFC-007 section 6.1).

    Numerator: changed paths, with churn outside ``allowed_paths`` counted
    double. Denominator: the sanctioned edit surface (``allowed_paths`` count).
    A minimal edit touching only allowed files scores low; sprawl inflates it.
    This is a *path*-level proxy -- line-level churn against the reference
    variant's diff needs that diff and is filed as a follow-up.
    """
    numerator = len(result.changed_paths) + len(result.unexpected_paths)
    return round(numerator / max(allowed_path_count, 1), 4)


def count_process_violations(
    run: AgentRun, *, test_needle: str = _SANDBOX_TEST_NEEDLE
) -> int:
    """Count contract-free ``agent_verifiers`` failures over a run (RFC-007 6.1).

    Applies only the sandbox-applicable, contract-free checks that pass
    vacuously when the behaviour is absent: no-commit-while-red and
    questions-are-multiple-choice. A harness that commits on red, or asks a
    free-form (non multiple-choice) question, trips one. Order/branch/PR-body
    verifiers need a per-scenario contract and are out of the honest sandbox
    set today.
    """
    violations = 0
    try:
        assert_no_commit_while_tests_red(run, test_needle=test_needle)
    except VerificationFailure:
        violations += 1
    try:
        assert_questions_are_multiple_choice(run)
    except VerificationFailure:
        violations += 1
    return violations


def derive_outcome(result: SandboxResult) -> str:
    """Honest session outcome (post-#249): never hardcoded to success.

    ``failed`` -- timed out or tests red (task not solved). ``partial`` -- tests
    green but the harness sprawled outside ``allowed_paths``. ``success`` --
    tests green and the edit stayed in bounds.
    """
    if result.timed_out or not result.tests_passed:
        return "failed"
    if result.has_unexpected_churn:
        return "partial"
    return "success"


def compute_metrics(result: SandboxResult, allowed_path_count: int) -> dict[str, float]:
    """The reserved-key metrics honestly capturable from a SandboxResult today.

    ``tokens_in``/``tokens_out`` (#268) are recorded when the harness transcript
    reported them onto ``result.run`` -- the live adapters parse them from the
    CLI's own usage events (opencode / claude-code / codex). They are OMITTED
    (not a phantom zero) when the run carries the ``-1`` unknown sentinel: a
    scripted stand-in, or a harness whose transcript surfaced no usage. This
    keeps the metric set honest about what a given run actually measured.
    ``grader_score`` is llm_judge-only and not produced by the exec-graded
    sandbox. ``sandbox_exec_overhead_ms`` (#381) is added -- as the mean per-call
    broker overhead -- only when the run actually routed code-exec through the
    broker (a container-routed harness), so a scripted or un-routed run records
    no phantom-zero cost.
    """
    metrics = {
        METRIC_TASK_SUCCESS: compute_task_success(result),
        METRIC_CHURN_RATIO: compute_churn_ratio(result, allowed_path_count),
        METRIC_PROCESS_VIOLATIONS: float(count_process_violations(result.run)),
        METRIC_LATENCY_MS: round(result.duration_seconds * 1000.0, 3),
    }
    if result.run.tokens_in >= 0:
        metrics[METRIC_TOKENS_IN] = float(result.run.tokens_in)
    if result.run.tokens_out >= 0:
        metrics[METRIC_TOKENS_OUT] = float(result.run.tokens_out)
    samples = result.sandbox_exec_overhead_ms
    if samples:
        metrics[METRIC_SANDBOX_EXEC_OVERHEAD_MS] = round(sum(samples) / len(samples), 4)
    return metrics


def default_legs(
    *, include_claude: bool = False, opencode_model: str = ""
) -> list[HarnessLeg]:
    """The Wave-3 available-harness set: opencode (Tier A) + optional claude (Tier B).

    ``codex`` is omitted (absent on this box; it would join Tier A when
    installed). ``claude-code`` cannot pin the local model (RFC-008), so it is
    Tier B -- descriptive only, never placed in a Tier-A comparison cell.
    """
    legs = [
        HarnessLeg(harness="opencode", model=opencode_model, tier=TIER_A_FIXED_LOCAL)
    ]
    if include_claude:
        legs.append(HarnessLeg(harness="claude-code", model="", tier=TIER_B_NATIVE))
    return legs


class HarnessComparison:
    """Run the sandbox battery under each harness, N repeats, write the spine.

    Deterministic by construction: the DB, the :class:`AgentSandbox` (whose
    agent invoker is injectable), the session-id factory, and the clock are all
    injected, so the metric-writing path is exercised against hermetic sqlite
    with no models.
    """

    def __init__(
        self,
        sandbox: AgentSandbox,
        db: HarnessDatabase,
        *,
        repeats: int = DEFAULT_REPEATS,
        opencode_config: Path | None = None,
        session_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
        branch: str = "",
        digest_resolver: Callable[[str], str] | None = None,
    ) -> None:
        if repeats < 1:
            raise ValueError(f"repeats must be >= 1, got {repeats}")
        self._sandbox = sandbox
        self._db = db
        self._repeats = int(repeats)
        self._opencode_config = opencode_config or _DEFAULT_OPENCODE_CONFIG
        self._new_id = session_id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or _utc_now
        self._branch = branch
        # RFC-008 A3 (#242): resolves model_id -> content digest for the spine.
        # Injected (like the clock and id factory) so the metric-writing path stays
        # deterministic — a resolver that reaches Ollama has no place in the hermetic
        # twin. Left None in the production wiring below: this exec-graded runner
        # only knows opencode's `provider/model` ref, and mapping that to an Ollama
        # tag+digest is separate plumbing; a fabricated digest would be a dishonest
        # coordinate (the very failure §5 forbids). The live digest path is exercised
        # by dialog_replay, which holds the provider itself.
        self._digest_resolver = digest_resolver

    def run(
        self,
        scenarios: Sequence[SandboxScenario | Path | str],
        legs: Sequence[HarnessLeg],
        *,
        battery_run_id: str = "",
    ) -> ComparisonReport:
        """Run every (scenario x leg x repeat) and write one spine row each.

        A shared ``battery_run_id`` groups all legs of this invocation so
        repeats and harness pairs join. An absent harness CLI skips the whole
        leg cleanly (skip-and-log per CLAUDE.md), recording nothing for it.
        """
        if not legs:
            raise ValueError("no harness legs to compare")
        battery_run_id = battery_run_id or self._new_id()

        # Hard-block on #191/#273 before any Tier-A leg runs (RFC-007 s5/s11): the
        # gate now verifies the SELECTED model resolves to a declared LOCAL
        # provider, and it arms for ANY Tier-A leg (not just opencode), so a
        # mislabeled Tier-A leg cannot slip past by omitting opencode. The gate
        # returns a VerifiedLocalModel token (#278) that the row then requires.
        verified_local_model: VerifiedLocalModel | None = None
        config_data: dict = {}
        if any(leg.tier == TIER_A_FIXED_LOCAL for leg in legs):
            config_data = load_opencode_config(self._opencode_config)
            verified_local_model = gate_config(
                config_data, source=f"opencode.json ({self._opencode_config})"
            )

        resolved = [self._resolve(s) for s in scenarios]
        rows: list[ComparisonRow] = []
        skipped: list[tuple[str, str]] = []

        for leg in legs:
            model_id, verified_model = self._leg_model(
                leg, verified_local_model, config_data
            )
            leg_available = True
            for scenario in resolved:
                if not leg_available:
                    break
                for repeat_idx in range(self._repeats):
                    try:
                        result = self._sandbox.run_scenario(
                            scenario,
                            variant=leg.harness,
                            agent_id=leg.harness,
                            harness=leg.harness,
                            harness_model=leg.model,
                        )
                    except HarnessNotAvailableError:
                        leg_available = False
                        reason = f"{leg.harness} CLI not available"
                        logger.info(
                            f"harness comparison: skipping leg {leg.harness!r} "
                            f"(tier {leg.tier}) -- {reason}"
                        )
                        skipped.append((leg.harness, reason))
                        break
                    except LiveHarnessNotRoutedError:
                        # #377: the harness runs, but its code-exec is still
                        # host-native (F5 gap), so a container-verified row would
                        # be a silent lie. Record the leg as skipped with the
                        # honest reason -- NEVER a fabricated success/failure row.
                        leg_available = False
                        reason = f"{leg.harness} exec-routing not wired (F5, #377)"
                        logger.info(
                            f"harness comparison: skipping leg {leg.harness!r} "
                            f"(tier {leg.tier}) -- {reason}"
                        )
                        skipped.append((leg.harness, reason))
                        break
                    rows.append(
                        self._record(
                            scenario,
                            leg,
                            model_id,
                            verified_model,
                            repeat_idx,
                            battery_run_id,
                            result,
                        )
                    )
        return ComparisonReport(
            battery_run_id=battery_run_id,
            rows=tuple(rows),
            skipped=tuple(skipped),
        )

    def _record(
        self,
        scenario: SandboxScenario,
        leg: HarnessLeg,
        model_id: str,
        verified_model: VerifiedLocalModel | None,
        repeat_idx: int,
        battery_run_id: str,
        result: SandboxResult,
    ) -> ComparisonRow:
        session_id = self._new_id()
        started_at = self._clock()
        ended_at = self._clock()
        outcome = derive_outcome(result)
        metrics = compute_metrics(result, len(scenario.allowed_paths))
        # Build the row FIRST: ComparisonRow enforces the Tier-A -> gate-verified
        # local model TOKEN invariant in __post_init__, so a mislabeled leg raises
        # ComparabilityError BEFORE any DB write -- no half-persisted, dishonest
        # spine row is ever left behind (#273/#278).
        row = ComparisonRow(
            scenario_id=scenario.scenario_id,
            battery_run_id=battery_run_id,
            harness=leg.harness,
            model_id=model_id,
            tier=leg.tier,
            repeat_idx=repeat_idx,
            session_id=session_id,
            outcome=outcome,
            metrics=metrics,
            verified_model=verified_model,
            sandbox_exec_overhead_ms=result.sandbox_exec_overhead_ms,
        )
        # save_harness FIRST: agentic_metrics carries a FK on session_id. repeat_idx
        # is persisted to the spine (#277) so S4 pairs on the stored (scenario_id,
        # repeat_idx) key -- not fragile row order -- and a skipped repeat leaves a
        # visible hole in the stored indices rather than a silently shifted run.
        self._db.save_harness(
            AgenticHarness(
                session_id=session_id,
                tool_name=leg.harness,
                started_at=started_at,
                model_id=model_id,
                rfc_version=__version__,
                branch=self._branch,
                ended_at=ended_at,
                outcome=outcome,
                scenario_id=scenario.scenario_id,
                battery_run_id=battery_run_id,
                repeat_idx=repeat_idx,
                model_digest=self._resolve_digest(model_id),
                # #350: persist the local-resolution verdict from the token the row
                # already carries -- the token IS the tier. The row was built above
                # and passed __post_init__, so this is the gate's own verdict
                # (fail-closed to 0/Tier B for any untokened leg), carried onto the
                # durable spine for the scoreboard view to read at read time.
                verified_local=1 if row.verified_local else 0,
            )
        )
        self._db.save_metrics(
            [
                AgenticMetric(
                    session_id=session_id,
                    metric_key=key,
                    recorded_at=ended_at,
                    metric_value=value,
                )
                for key, value in metrics.items()
            ]
        )
        return row

    def _resolve_digest(self, model_id: str) -> str:
        """Resolve ``model_id`` to a content digest for the spine, "" when unknown.

        Exception-safe (like the digest resolver it wraps): any failure yields ""
        (NULL) so a digest lookup can never break the metric write. Returns "" when
        no resolver was injected — the deterministic default.
        """
        if not self._digest_resolver or not model_id:
            return ""
        try:
            return self._digest_resolver(model_id) or ""
        except Exception:  # pragma: no cover - defensive: digest must never break a run
            return ""

    def _resolve(self, scenario: SandboxScenario | Path | str) -> SandboxScenario:
        if isinstance(scenario, SandboxScenario):
            return scenario
        path = Path(scenario)
        if not path.is_absolute() and not path.is_dir():
            path = DEFAULT_SANDBOX_SCENARIOS_ROOT / str(scenario)
        return load_sandbox_scenario(path)

    @staticmethod
    def _leg_model(
        leg: HarnessLeg,
        verified_local_model: VerifiedLocalModel | None,
        config: dict,
    ) -> tuple[str, VerifiedLocalModel | None]:
        """Resolve ``(model_id, verification token)`` for a leg, fail-closed for Tier A.

        Tier A ("fixed local model"): an explicit override must ITSELF resolve to
        a declared local provider (so ``--opencode-model`` cannot smuggle a remote
        model past the config gate), minting its own token; with no override,
        ``opencode`` takes the gate-verified local default token, and any other
        harness resolves to ``("", None)`` -- which :class:`ComparisonRow` then
        rejects for lack of a token, because this runner has no way to pin a
        non-opencode harness to the local model (RFC-008). Tier B: the native
        model is recorded as-is with no token (descriptive only).
        """
        if leg.tier == TIER_A_FIXED_LOCAL:
            if leg.model:
                token = assert_model_resolves_local(
                    leg.model, config, source=f"Tier-A {leg.harness} model override"
                )
                return token.model_id, token
            if leg.harness == "opencode" and verified_local_model is not None:
                # gate-verified opencode.json default token
                return verified_local_model.model_id, verified_local_model
            # non-opencode Tier-A (or an unreachable missing-gate state): no local
            # pin here -> ComparisonRow rejects for lack of a token.
            return "", None
        return leg.model, None  # Tier B: native model, descriptive only


def run_comparison(
    *,
    database_url: str,
    scenarios: Sequence[str] = DEFAULT_BATTERY_SCENARIOS,
    repeats: int = DEFAULT_REPEATS,
    include_claude: bool = False,
    opencode_model: str = "",
    agent_id: str = "claude-code",
    battery_run_id: str = "",
    branch: str = "",
) -> ComparisonReport:
    """Production wiring: real sandbox caps + real DB, over the default battery.

    ``agent_id`` names the ``local_agents.yaml`` agent whose ``sandbox:`` block
    supplies the Docker resource caps (default ``claude-code``).
    """
    from rfc.agent_config import load_agent_config

    config = load_agent_config(agent_id)
    if config.sandbox is None:
        raise ValueError(
            f"agent {agent_id!r} declares no sandbox: block -- tier:4 comparison "
            "needs resource caps (image, cpu_cores, memory_mb, wall_clock_seconds)"
        )
    sandbox = AgentSandbox(limits=config.sandbox)
    db = HarnessDatabase(database_url=database_url)
    runner = HarnessComparison(sandbox, db, repeats=repeats, branch=branch)
    legs = default_legs(include_claude=include_claude, opencode_model=opencode_model)
    return runner.run(scenarios, legs, battery_run_id=battery_run_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rfc-harness-comparison", description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        default=[],
        help="scenario id (repeatable); defaults to the two quality-barred sandbox scenarios",
    )
    parser.add_argument(
        "--include-claude",
        action="store_true",
        help="add the Tier-B claude-code leg (native model, descriptive only)",
    )
    parser.add_argument("--opencode-model", default="")
    parser.add_argument(
        "--agent",
        default="claude-code",
        help="local_agents.yaml agent id whose sandbox: block supplies caps",
    )
    parser.add_argument("--battery-run-id", default="")
    return parser


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        print(
            "ERROR: no database configured -- pass --database-url or set "
            "DATABASE_URL (the spine rows are the point of comparison mode).",
            file=sys.stderr,
        )
        return 2
    scenarios = args.scenarios or list(DEFAULT_BATTERY_SCENARIOS)
    try:
        report = run_comparison(
            database_url=url,
            scenarios=scenarios,
            repeats=args.repeats,
            include_claude=args.include_claude,
            opencode_model=args.opencode_model,
            agent_id=args.agent,
            battery_run_id=args.battery_run_id,
        )
    except ComparabilityError as exc:
        print(f"ERROR: comparability gate failed (#191): {exc}", file=sys.stderr)
        return 3
    skipped = [harness for harness, _ in report.skipped]
    print(
        f"battery_run_id={report.battery_run_id} "
        f"rows={len(report.rows)} skipped={skipped}"
    )
    for row in report.rows:
        print(
            f"  {row.scenario_id} {row.harness} tier={row.tier} "
            f"repeat={row.repeat_idx} outcome={row.outcome} "
            f"task_success={row.metrics.get(METRIC_TASK_SUCCESS)}"
        )
    return 0


class HarnessComparisonKeywords:
    """Robot keyword surface for RFC-007 S2 comparison mode (#218).

    A thin wrapper over :func:`run_comparison` so the tier:4 ``harness_matrix``
    suite can drive one bounded live battery. The deterministic coverage is
    ``tests/test_harness_comparison.py``; this surface is for the gated live
    smoke only.
    """

    ROBOT_LIBRARY_SCOPE = "SUITE"

    @keyword("Run Harness Comparison Battery")
    def run_harness_comparison_battery(
        self,
        database_url: str,
        repeats: int = 1,
        include_claude: bool = False,
        opencode_model: str = "",
        scenarios: "Sequence[str] | None" = None,
    ) -> ComparisonReport:
        """Run the battery under each available harness and return the report."""
        return run_comparison(
            database_url=database_url,
            scenarios=tuple(scenarios) if scenarios else DEFAULT_BATTERY_SCENARIOS,
            repeats=int(repeats),
            include_claude=bool(include_claude),
            opencode_model=opencode_model,
        )

    @keyword("Comparison Report Should Have Rows For")
    def comparison_report_should_have_rows_for(
        self, report: ComparisonReport, harness: str
    ) -> None:
        """Assert at least one spine row was written for ``harness``."""
        seen = sorted({row.harness for row in report.rows})
        if harness not in seen:
            raise AssertionError(
                f"no comparison rows for harness {harness!r}; got {seen} "
                f"(skipped: {[h for h, _ in report.skipped]})"
            )


if __name__ == "__main__":
    raise SystemExit(main())
