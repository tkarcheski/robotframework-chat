"""Deterministic twin for RFC-007 S2 comparison mode (#218).

Exercises the whole metric-writing path against hermetic sqlite with no models,
no Docker, and no tokens: a stub sandbox for the combinatorial pairing/tier/skip
cases, and one faithful end-to-end run through the real ``AgentSandbox`` live
path (fake container manager + replayed transcript).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from rfc.agent_config import SandboxLimits
from rfc.agent_run import AgentCommand, AgentQuestion, AgentRun
from rfc.agent_sandbox import AgentSandbox, SandboxResult
from rfc.churn_manifest import parse_manifest
from rfc.exceptions import HarnessNotAvailableError
from rfc.harness_adapters import ClaudeProcessResult
from rfc.harness_comparison import (
    TIER_A_FIXED_LOCAL,
    TIER_B_NATIVE,
    ComparabilityError,
    ComparisonRow,
    HarnessComparison,
    HarnessLeg,
    _DEFAULT_OPENCODE_CONFIG,
    assert_opencode_comparable,
    build_parser,
    main,
    compute_churn_ratio,
    compute_metrics,
    compute_task_success,
    count_process_violations,
    default_legs,
    derive_outcome,
)
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import (
    METRIC_CHURN_RATIO,
    METRIC_LATENCY_MS,
    METRIC_PROCESS_VIOLATIONS,
    METRIC_TASK_SUCCESS,
)
from rfc.opencode_config import VerifiedLocalModel, assert_model_resolves_local

# A minimal declared-local opencode config the gate accepts, for minting real
# VerifiedLocalModel tokens in the Tier-A invariant tests (#278).
_LOCAL_CFG = {
    "model": "ollama/my-model",
    "provider": {
        "ollama": {
            "options": {"baseURL": "http://localhost:11434/v1"},
            "models": {"my-model": {}},
        }
    },
}


def _local_token(model_ref: str = "ollama/my-model") -> VerifiedLocalModel:
    """Mint a genuine gate-verified token for a Tier-A row test."""
    return assert_model_resolves_local(model_ref, _LOCAL_CFG, source="test")


FIXED_CLOCK = "2026-07-13T00:00:00Z"


def _id_factory():
    counter = {"n": 0}

    def factory() -> str:
        counter["n"] += 1
        return f"sid-{counter['n']:04d}"

    return factory


def _run(*, questions=(), commands=()) -> AgentRun:
    return AgentRun(
        agent_id="opencode",
        scenario_id="tier4_bug_fix",
        task="fix it",
        base_branch="claude-code-staging",
        branch_name="opencode/x",
        commands=tuple(commands),
        questions=tuple(questions),
    )


def _result(
    *,
    tests_exit: int = 0,
    changed=("calculator.py",),
    unexpected=(),
    timed_out: bool = False,
    duration: float = 0.25,
    run: AgentRun | None = None,
) -> SandboxResult:
    return SandboxResult(
        scenario_id="tier4_bug_fix",
        agent_id="opencode",
        variant="opencode",
        agent_exit_code=124 if timed_out else 0,
        agent_output_tail="",
        tests_exit_code=tests_exit,
        tests_output_tail="",
        changed_paths=tuple(changed),
        unexpected_paths=tuple(unexpected),
        duration_seconds=duration,
        run=run or _run(),
        timed_out=timed_out,
    )


class StubSandbox:
    """Duck-typed AgentSandbox: returns a canned result (or raises), records calls."""

    def __init__(
        self, result: SandboxResult | None = None, raises: Exception | None = None
    ) -> None:
        self._result = result if result is not None else _result()
        self._raises = raises
        self.calls: list[dict] = []

    def run_scenario(
        self, scenario, *, variant, agent_id, harness, harness_model
    ) -> SandboxResult:
        self.calls.append(
            {
                "scenario_id": scenario.scenario_id,
                "variant": variant,
                "agent_id": agent_id,
                "harness": harness,
                "model": harness_model,
            }
        )
        if self._raises is not None:
            raise self._raises
        return self._result


def _runner(sandbox, db, **kw) -> HarnessComparison:
    return HarnessComparison(
        sandbox,
        db,
        session_id_factory=_id_factory(),
        clock=lambda: FIXED_CLOCK,
        **kw,
    )


def _db(tmp_path: Path) -> HarnessDatabase:
    return HarnessDatabase(db_path=str(tmp_path / "harness.db"))


# ---------------------------------------------------------------------------
# Pure metric derivation.
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_task_success_happy(self) -> None:
        assert compute_task_success(_result()) == 1.0

    def test_task_success_unexpected_churn_fails(self) -> None:
        r = _result(changed=("calculator.py", "junk.log"), unexpected=("junk.log",))
        assert compute_task_success(r) == 0.0

    def test_task_success_timeout_fails(self) -> None:
        assert compute_task_success(_result(timed_out=True)) == 0.0

    def test_task_success_red_tests_fail(self) -> None:
        assert compute_task_success(_result(tests_exit=1)) == 0.0

    def test_churn_ratio_minimal_edit(self) -> None:
        assert compute_churn_ratio(_result(), allowed_path_count=1) == 1.0

    def test_churn_ratio_counts_unexpected_double(self) -> None:
        r = _result(changed=("calculator.py", "junk.log"), unexpected=("junk.log",))
        # (2 changed + 1 unexpected) / 1 allowed == 3.0
        assert compute_churn_ratio(r, allowed_path_count=1) == 3.0

    def test_process_violations_clean_run_zero(self) -> None:
        assert count_process_violations(_run()) == 0

    def test_process_violations_flags_non_multiple_choice_question(self) -> None:
        q = AgentQuestion(text="what now?", options=("only-one",))
        assert count_process_violations(_run(questions=(q,))) == 1

    def test_process_violations_flags_commit_while_red(self) -> None:
        cmd = AgentCommand(
            argv=("bash", "-lc", "python -m unittest; git commit -m wip"),
            returncode=0,
        )
        assert count_process_violations(_run(commands=(cmd,))) == 1

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({}, "success"),
            ({"changed": ("calculator.py", "j"), "unexpected": ("j",)}, "partial"),
            ({"tests_exit": 1}, "failed"),
            ({"timed_out": True}, "failed"),
        ],
    )
    def test_derive_outcome(self, kwargs, expected) -> None:
        assert derive_outcome(_result(**kwargs)) == expected

    def test_compute_metrics_only_capturable_reserved_keys(self) -> None:
        metrics = compute_metrics(_result(duration=0.5), allowed_path_count=1)
        assert set(metrics) == {
            METRIC_TASK_SUCCESS,
            METRIC_CHURN_RATIO,
            METRIC_PROCESS_VIOLATIONS,
            METRIC_LATENCY_MS,
        }
        assert metrics[METRIC_LATENCY_MS] == 500.0


# ---------------------------------------------------------------------------
# Comparability gate (#191 hard-block).
# ---------------------------------------------------------------------------


class TestComparabilityGate:
    def test_repo_opencode_json_is_comparable(self) -> None:
        model = assert_opencode_comparable(_DEFAULT_OPENCODE_CONFIG)
        assert model.startswith("ollama/")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ComparabilityError, match="not found"):
            assert_opencode_comparable(tmp_path / "nope.json")

    def test_missing_model_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "opencode.json"
        cfg.write_text(json.dumps({"provider": {}}))
        with pytest.raises(ComparabilityError, match="no top-level 'model'"):
            assert_opencode_comparable(cfg)

    def test_external_baseurl_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "opencode.json"
        cfg.write_text(
            json.dumps(
                {
                    "model": "ollama/x",
                    "provider": {
                        "ollama": {"options": {"baseURL": "https://api.example.com/v1"}}
                    },
                }
            )
        )
        with pytest.raises(ComparabilityError, match="not local"):
            assert_opencode_comparable(cfg)


# ---------------------------------------------------------------------------
# Runner over a stub sandbox: pairing, spine rows, tiers, model pinning, skips.
# ---------------------------------------------------------------------------


class TestComparisonRunner:
    def test_writes_one_row_per_scenario_harness_repeat(self, tmp_path: Path) -> None:
        stub = StubSandbox()
        runner = _runner(stub, _db(tmp_path), repeats=2)
        report = runner.run(
            ["tier4_bug_fix", "tier4_regression_guard"],
            [HarnessLeg("opencode")],
            battery_run_id="batt-1",
        )
        assert len(report.rows) == 4
        assert {r.battery_run_id for r in report.rows} == {"batt-1"}
        # Paired by (scenario_id, repeat_idx): each scenario has repeats 0 and 1.
        by_scenario: dict[str, set[int]] = {}
        for row in report.rows:
            by_scenario.setdefault(row.scenario_id, set()).add(row.repeat_idx)
        assert by_scenario == {
            "tier4_bug_fix": {0, 1},
            "tier4_regression_guard": {0, 1},
        }
        assert len(stub.calls) == 4
        assert all(c["harness"] == "opencode" for c in stub.calls)

    def test_writes_spine_harness_and_metric_rows(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        stub = StubSandbox(_result())
        runner = _runner(stub, db, repeats=1)
        report = runner.run(
            ["tier4_bug_fix"], [HarnessLeg("opencode")], battery_run_id="batt-9"
        )
        row = report.rows[0]
        stored = db.get_harness(row.session_id)
        assert stored is not None
        assert stored.tool_name == "opencode"
        assert stored.scenario_id == "tier4_bug_fix"
        assert stored.battery_run_id == "batt-9"
        assert stored.outcome == "success"
        assert stored.model_id.startswith("ollama/")
        metrics = {m.metric_key: m.metric_value for m in db.get_metrics(row.session_id)}
        assert metrics[METRIC_TASK_SUCCESS] == 1.0
        assert metrics[METRIC_CHURN_RATIO] == 1.0
        assert metrics[METRIC_PROCESS_VIOLATIONS] == 0.0
        assert METRIC_LATENCY_MS in metrics
        # No digest resolver injected: model_digest is "" (NULL) by default (#242).
        assert stored.model_digest == ""

    def test_injected_digest_resolver_populates_model_digest(
        self, tmp_path: Path
    ) -> None:
        # RFC-008 A3 (#242): the injectable, deterministic resolver records the
        # model's content digest on the spine row (like clock / id factory).
        db = _db(tmp_path)
        seen: list[str] = []

        def resolver(model_id: str) -> str:
            seen.append(model_id)
            return "sha256:opencode-digest"

        runner = _runner(
            db=db, sandbox=StubSandbox(_result()), repeats=1, digest_resolver=resolver
        )
        report = runner.run(
            ["tier4_bug_fix"], [HarnessLeg("opencode")], battery_run_id="b-d"
        )
        stored = db.get_harness(report.rows[0].session_id)
        assert stored is not None
        assert stored.model_digest == "sha256:opencode-digest"
        assert seen == [stored.model_id]  # resolver was called with the row's model_id

    def test_digest_resolver_failure_is_swallowed(self, tmp_path: Path) -> None:
        # A resolver that raises must never break the metric write (skip-and-log).
        db = _db(tmp_path)

        def boom(_model_id: str) -> str:
            raise RuntimeError("ollama offline")

        runner = _runner(
            db=db, sandbox=StubSandbox(_result()), repeats=1, digest_resolver=boom
        )
        report = runner.run(
            ["tier4_bug_fix"], [HarnessLeg("opencode")], battery_run_id="b-e"
        )
        stored = db.get_harness(report.rows[0].session_id)
        assert stored is not None
        assert stored.model_digest == ""

    def test_production_wiring_leaves_model_digest_null_never_fabricated(
        self, tmp_path: Path
    ) -> None:
        # RFC-008 A3 honesty (#242): run_comparison constructs the runner with NO
        # digest_resolver, so production rows carry NULL model_digest — the field is
        # genuinely UNWIRED (a fabricated digest would be the §5-forbidden dishonest
        # coordinate), not merely coincidentally empty. Pin both facts.
        db = _db(tmp_path)
        runner = _runner(db=db, sandbox=StubSandbox(_result()), repeats=1)
        assert runner._digest_resolver is None  # unwired, not defaulted-away
        report = runner.run(
            ["tier4_bug_fix"], [HarnessLeg("opencode")], battery_run_id="b-null"
        )
        stored = db.get_harness(report.rows[0].session_id)
        assert stored is not None
        assert stored.model_digest == ""

    def test_repeat_idx_persisted_to_spine_for_pairing(self, tmp_path: Path) -> None:
        # #277: S4 pairs on the STORED (scenario_id, repeat_idx) key, so every
        # in-memory pair must be reconstructable straight from the spine -- not
        # inferred from row order. repeat 0 must persist as 0 (not NULL/-1).
        db = _db(tmp_path)
        stub = StubSandbox()
        runner = _runner(stub, db, repeats=3)
        report = runner.run(
            ["tier4_bug_fix", "tier4_regression_guard"],
            [HarnessLeg("opencode")],
            battery_run_id="batt-pair",
        )
        spine_pairs: set[tuple[str, int]] = set()
        for row in report.rows:
            stored = db.get_harness(row.session_id)
            assert stored is not None
            # The stored key equals the in-memory index -- persisted, never -1.
            assert stored.repeat_idx == row.repeat_idx
            assert stored.repeat_idx >= 0
            spine_pairs.add((stored.scenario_id, stored.repeat_idx))
        assert spine_pairs == {
            ("tier4_bug_fix", 0),
            ("tier4_bug_fix", 1),
            ("tier4_bug_fix", 2),
            ("tier4_regression_guard", 0),
            ("tier4_regression_guard", 1),
            ("tier4_regression_guard", 2),
        }

    def test_tags_cost_tiers(self, tmp_path: Path) -> None:
        stub = StubSandbox()
        runner = _runner(stub, _db(tmp_path), repeats=1)
        report = runner.run(
            ["tier4_bug_fix"],
            default_legs(include_claude=True),
            battery_run_id="batt-t",
        )
        tiers = {r.harness: r.tier for r in report.rows}
        assert tiers == {"opencode": TIER_A_FIXED_LOCAL, "claude-code": TIER_B_NATIVE}

    def test_opencode_pins_local_model_claude_does_not(self, tmp_path: Path) -> None:
        stub = StubSandbox()
        runner = _runner(stub, _db(tmp_path), repeats=1)
        report = runner.run(
            ["tier4_bug_fix"],
            default_legs(include_claude=True),
            battery_run_id="batt-m",
        )
        models = {r.harness: r.model_id for r in report.rows}
        assert models["opencode"].startswith("ollama/")
        # claude-code cannot pin a local model -> recorded blank, never cross-compared.
        assert models["claude-code"] == ""

    def test_skips_unavailable_harness(self, tmp_path: Path) -> None:
        stub = StubSandbox(raises=HarnessNotAvailableError("codex"))
        runner = _runner(stub, _db(tmp_path), repeats=3)
        report = runner.run(
            ["tier4_bug_fix", "tier4_regression_guard"],
            [HarnessLeg("codex", tier=TIER_A_FIXED_LOCAL)],
            battery_run_id="batt-s",
        )
        assert report.rows == ()
        assert report.skipped == (("codex", "codex CLI not available"),)
        # Broke out after the first probe, not once per repeat.
        assert len(stub.calls) == 1

    def test_empty_legs_raises(self, tmp_path: Path) -> None:
        runner = _runner(StubSandbox(), _db(tmp_path))
        with pytest.raises(ValueError, match="no harness legs"):
            runner.run(["tier4_bug_fix"], [])

    def test_repeats_must_be_positive(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="repeats must be"):
            _runner(StubSandbox(), _db(tmp_path), repeats=0)

    def test_comparability_gate_blocks_before_any_run(self, tmp_path: Path) -> None:
        bad = tmp_path / "opencode.json"
        bad.write_text(json.dumps({"provider": {}}))
        stub = StubSandbox()
        runner = _runner(stub, _db(tmp_path), repeats=1, opencode_config=bad)
        with pytest.raises(ComparabilityError):
            runner.run(["tier4_bug_fix"], [HarnessLeg("opencode")])
        # Gate fires before the sandbox is touched.
        assert stub.calls == []

    def test_default_legs_toggle_claude(self) -> None:
        assert [leg.harness for leg in default_legs()] == ["opencode"]
        assert [leg.harness for leg in default_legs(include_claude=True)] == [
            "opencode",
            "claude-code",
        ]


# ---------------------------------------------------------------------------
# One faithful end-to-end run through the real AgentSandbox live path.
# ---------------------------------------------------------------------------

OPENCODE_FIX_TRANSCRIPT = (
    json.dumps(
        {
            "part": {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "sed -i 's/a + b/a - b/' calculator.py"},
                    "output": "",
                },
            }
        }
    )
    + "\n"
)


def _manifest(entries: dict[str, str]) -> dict:
    # Faithfully replay the in-container ``manifest_command`` wire format: records
    # are NUL-terminated (``sha256sum -z ... | sort -z``), never newline-separated
    # (#274). ``parse_manifest`` splits on NUL, so a newline-delimited stub would
    # collapse every path into one malformed record that reads as unexpected churn.
    text = "".join(f"{h}  /workspace/{p}\0" for p, h in entries.items())
    return {"stdout": text, "stderr": "", "exit_code": 0, "duration_ms": 1}


def test_manifest_fixture_speaks_parse_manifest_wire_format() -> None:
    """Cross-format guard (#282): the fake-container ``_manifest`` stub must emit
    the exact wire format the *production* ``parse_manifest`` reads, so a future
    manifest format change (as #274 flipped newline -> NUL) cannot silently skew
    the fake into phantom churn again.

    Proven against the REAL shipped parser, not a duplicated literal: two records
    in, two distinct records out. If the stub and ``parse_manifest`` ever disagree
    on the record terminator/separator, the round-trip collapses and this fails at
    the fixture -- instead of surfacing three layers down as a bogus ``partial``.
    """
    entries = {"calculator.py": "hash-a", "test_calculator.py": "hash-b"}
    assert parse_manifest(_manifest(entries)["stdout"]) == entries

    # Regression witness: the pre-#284 newline stub collapses under the NUL parser
    # into ONE malformed record -- the precise mechanism of the #282 red.
    newline_stub = "".join(f"{h}  /workspace/{p}\n" for p, h in entries.items())
    assert len(parse_manifest(newline_stub)) == 1


class _FakeContainerManager:
    def __init__(self, exec_results: list[dict]) -> None:
        self.exec_results = list(exec_results)

    def create_container(self, config, name=None) -> str:
        return "cid-1"

    def execute_command(self, container_id, command, timeout=30, workdir=None) -> dict:
        if self.exec_results:
            return self.exec_results.pop(0)
        return {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 1}

    def copy_to_container(self, container_id, host_path, container_path) -> None:
        pass

    def stop_container(self, container_id, timeout=10) -> None:
        pass


def _recording_invoker(stdout: str):
    def invoker(argv, cwd, env, timeout) -> ClaudeProcessResult:
        return ClaudeProcessResult(returncode=0, stdout=stdout, stderr="")

    return invoker


def _limits() -> SandboxLimits:
    return SandboxLimits(
        image="python:3.11-slim",
        cpu_cores=1.0,
        memory_mb=512,
        wall_clock_seconds=42,
        network_mode="none",
    )


class TestRealSandboxPath:
    def test_live_opencode_leg_writes_success_row(self, tmp_path: Path) -> None:
        # Live path exec order (#235: code-exec routes into /workspace via the
        # broker, so no host-side copy-back / workspace-clear): baseline manifest,
        # after manifest, tests -- the opencode transcript fixes calculator.py.
        fake = _FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old", "test_calculator.py": "t"}),
                _manifest({"calculator.py": "new", "test_calculator.py": "t"}),
                {"stdout": "OK", "stderr": "", "exit_code": 0, "duration_ms": 9},
            ]
        )
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_recording_invoker(OPENCODE_FIX_TRANSCRIPT),
        )
        db = _db(tmp_path)
        runner = _runner(sandbox, db, repeats=1)
        report = runner.run(
            ["tier4_bug_fix"], [HarnessLeg("opencode")], battery_run_id="batt-live"
        )
        assert len(report.rows) == 1
        row = report.rows[0]
        assert row.outcome == "success"
        assert row.metrics[METRIC_TASK_SUCCESS] == 1.0
        assert row.metrics[METRIC_CHURN_RATIO] == 1.0
        stored = db.get_harness(row.session_id)
        assert stored is not None and stored.scenario_id == "tier4_bug_fix"

    def test_real_sandbox_skips_absent_codex(self, tmp_path: Path) -> None:
        # No invoker injected -> the probe gate is armed; codex is never
        # installed, so the leg skips through the real production path.
        sandbox = AgentSandbox(limits=_limits(), manager=_FakeContainerManager([]))
        runner = _runner(sandbox, _db(tmp_path), repeats=2)
        report = runner.run(
            ["tier4_bug_fix"],
            [HarnessLeg("codex", tier=TIER_A_FIXED_LOCAL)],
            battery_run_id="batt-codex",
        )
        assert report.rows == ()
        assert report.skipped == (("codex", "codex CLI not available"),)


class TestCli:
    def test_build_parser_defaults(self) -> None:
        args = build_parser().parse_args([])
        assert args.repeats == 5
        assert args.scenarios == []
        assert args.include_claude is False
        assert args.agent == "claude-code"

    def test_main_without_database_url_returns_2(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert main([]) == 2

    def test_main_reports_comparability_failure_as_exit_3(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # A bad opencode.json makes run_comparison raise ComparabilityError;
        # main() must surface it as a clean non-zero exit, not a traceback.
        import rfc.harness_comparison as hc

        def _boom(**kwargs):
            raise ComparabilityError("opencode.json not local")

        monkeypatch.setattr(hc, "run_comparison", _boom)
        assert main(["--database-url", f"sqlite:///{tmp_path / 'h.db'}"]) == 3


# ---------------------------------------------------------------------------
# #273 regression: the gate must REQUIRE the selected model to resolve to a
# local provider, and Tier-A rows must be structurally impossible without a
# non-empty gate-verified local model_id. Each case below PASSED the gate (or
# wrote a Tier-A row) on the pre-fix HEAD -- they are the defect's own repros.
# ---------------------------------------------------------------------------


def _write_cfg(tmp_path: Path, cfg: dict) -> Path:
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps(cfg))
    return p


class TestGateRequiresLocalModel:
    def test_frontier_model_no_provider_block_fails(self, tmp_path: Path) -> None:
        # #273 repro 1: {"model": "openai/gpt-4o"} PASSED before -> now fail-closed.
        cfg = _write_cfg(tmp_path, {"model": "openai/gpt-4o"})
        with pytest.raises(ComparabilityError, match="not declared"):
            assert_opencode_comparable(cfg)

    def test_frontier_model_absent_baseurl_fails(self, tmp_path: Path) -> None:
        # #273 repro 2: provider present but options carry NO baseURL (builtin egress).
        cfg = _write_cfg(
            tmp_path,
            {"model": "anthropic/claude-3", "provider": {"anthropic": {"options": {}}}},
        )
        with pytest.raises(ComparabilityError, match="no baseURL"):
            assert_opencode_comparable(cfg)

    def test_remote_model_beside_unrelated_local_provider_fails(
        self, tmp_path: Path
    ) -> None:
        # #273 repro 3: remote model selected next to an unrelated LOCAL ollama.
        cfg = _write_cfg(
            tmp_path,
            {
                "model": "openai/gpt-4o",
                "provider": {
                    "ollama": {"options": {"baseURL": "http://localhost:11434"}}
                },
            },
        )
        with pytest.raises(ComparabilityError, match="not declared"):
            assert_opencode_comparable(cfg)

    def test_remote_baseurl_on_selected_provider_fails(self, tmp_path: Path) -> None:
        cfg = _write_cfg(
            tmp_path,
            {
                "model": "ollama/x",
                "provider": {
                    "ollama": {"options": {"baseURL": "https://api.example.com/v1"}}
                },
            },
        )
        with pytest.raises(ComparabilityError, match="not local"):
            assert_opencode_comparable(cfg)

    def test_bare_model_without_provider_prefix_fails(self, tmp_path: Path) -> None:
        cfg = _write_cfg(tmp_path, {"model": "gpt-4o"})
        with pytest.raises(ComparabilityError, match="provider/model"):
            assert_opencode_comparable(cfg)

    def test_model_not_served_by_local_provider_fails(self, tmp_path: Path) -> None:
        cfg = _write_cfg(
            tmp_path,
            {
                "model": "ollama/ghost",
                "provider": {
                    "ollama": {
                        "options": {"baseURL": "http://localhost:11434/v1"},
                        "models": {"real-model": {}},
                    }
                },
            },
        )
        with pytest.raises(ComparabilityError, match="not among the models"):
            assert_opencode_comparable(cfg)

    def test_local_selected_model_passes(self, tmp_path: Path) -> None:
        cfg = _write_cfg(
            tmp_path,
            {
                "model": "ollama/my-model",
                "provider": {
                    "ollama": {
                        "options": {"baseURL": "http://localhost:11434/v1"},
                        "models": {"my-model": {}},
                    }
                },
            },
        )
        assert assert_opencode_comparable(cfg) == "ollama/my-model"


class _NoWriteDB:
    """Duck-typed HarnessDatabase that only records save calls (never persists)."""

    def __init__(self) -> None:
        self.saved: list = []

    def save_harness(self, harness) -> str:
        self.saved.append(harness)
        return harness.session_id

    def save_metrics(self, metrics) -> list:
        self.saved.append(metrics)
        return []


class TestTierAStructuralInvariant:
    def test_comparison_row_tier_a_requires_verification_token(self) -> None:
        # #273/#278 facet 2, at the type: a Tier-A row without a gate-minted
        # VerifiedLocalModel token cannot exist, even if model_id is non-empty.
        # A future runner building ComparisonRow(tier="A", model_id="openai/gpt-4o")
        # directly (non-empty, remote) is now rejected -- it has no token.
        with pytest.raises(ComparabilityError, match="no gate-verified local model"):
            ComparisonRow(
                scenario_id="tier4_bug_fix",
                battery_run_id="b",
                harness="claude-code",
                model_id="openai/gpt-4o",
                tier=TIER_A_FIXED_LOCAL,
                repeat_idx=0,
                session_id="s",
                outcome="success",
                metrics={},
            )

    def test_comparison_row_tier_a_accepts_verified_token(self) -> None:
        # #278: with a genuine gate-minted token whose model_id matches, the
        # Tier-A row constructs normally.
        token = _local_token()
        row = ComparisonRow(
            scenario_id="tier4_bug_fix",
            battery_run_id="b",
            harness="opencode",
            model_id="ollama/my-model",
            tier=TIER_A_FIXED_LOCAL,
            repeat_idx=0,
            session_id="s",
            outcome="success",
            metrics={},
            verified_model=token,
        )
        assert row.model_id == "ollama/my-model"
        assert row.verified_model is token

    def test_comparison_row_tier_a_rejects_token_for_a_different_model(self) -> None:
        # #278: a token attests exactly one model; a row cannot carry a token for a
        # different model than the model_id it records (no launder-through-token).
        token = _local_token("ollama/my-model")
        with pytest.raises(ComparabilityError, match="attests"):
            ComparisonRow(
                scenario_id="tier4_bug_fix",
                battery_run_id="b",
                harness="opencode",
                model_id="ollama/some-other-model",
                tier=TIER_A_FIXED_LOCAL,
                repeat_idx=0,
                session_id="s",
                outcome="success",
                metrics={},
                verified_model=token,
            )

    def test_duck_typed_token_fake_is_rejected_at_runtime(self) -> None:
        # Forge attempt (test-design, #313 sweep item 6): a SimpleNamespace with a
        # matching .model_id used to pass the row's duck-typed check (rejected only
        # by mypy, which an adversarial in-process caller does not run). FLIPPED
        # from possible-forge to fail-closed by #314: the row now requires the
        # EXACT VerifiedLocalModel type, so the fake is refused at runtime.
        from types import SimpleNamespace

        with pytest.raises(ComparabilityError, match="exact"):
            ComparisonRow(
                scenario_id="tier4_bug_fix",
                battery_run_id="b",
                harness="opencode",
                model_id="openai/gpt-4o",
                tier=TIER_A_FIXED_LOCAL,
                repeat_idx=0,
                session_id="s",
                outcome="success",
                metrics={},
                verified_model=SimpleNamespace(  # type: ignore[arg-type]
                    model_id="openai/gpt-4o"
                ),
            )

    def test_post_init_overriding_subclass_token_is_rejected(self) -> None:
        # Forge attempt (test-design, #313 sweep item 5): a VerifiedLocalModel
        # subclass overriding __post_init__ skipped the mint check AND passed the
        # row's duck-typed check -- mypy-clean, so it was the most dangerous of the
        # four #313 forge paths. FLIPPED from possible-forge to fail-closed by
        # #314: type() is compared exactly, so a subclass is not gate verification.
        class ForgedToken(VerifiedLocalModel):
            def __post_init__(self, _mint_key: object) -> None:
                pass  # skip the mint check entirely

        forged = ForgedToken("openai/gpt-4o")  # constructs fine; row must refuse
        with pytest.raises(ComparabilityError, match="exact"):
            ComparisonRow(
                scenario_id="tier4_bug_fix",
                battery_run_id="b",
                harness="opencode",
                model_id="openai/gpt-4o",
                tier=TIER_A_FIXED_LOCAL,
                repeat_idx=0,
                session_id="s",
                outcome="success",
                metrics={},
                verified_model=forged,
            )

    def test_object_dunder_new_fabrication_remains_documented_possible(self) -> None:
        # Forge path (test-design, #313 sweep item 8) that REMAINS after #314:
        # object.__new__ + object.__setattr__ fabricates a real-typed token
        # bypassing __init__/__post_init__ entirely -- inherent to every Python
        # capability object and explicitly ruled OUT of #314's scope by design
        # (review + dual sign-off is the defense; an in-process absolute is
        # impossible). This test documents the exact boundary of the guarantee:
        # if it ever starts failing, the docs' honesty wording must be revisited.
        fabricated = object.__new__(VerifiedLocalModel)
        object.__setattr__(fabricated, "model_id", "openai/gpt-4o")
        row = ComparisonRow(
            scenario_id="tier4_bug_fix",
            battery_run_id="b",
            harness="opencode",
            model_id="openai/gpt-4o",
            tier=TIER_A_FIXED_LOCAL,
            repeat_idx=0,
            session_id="s",
            outcome="success",
            metrics={},
            verified_model=fabricated,
        )
        assert row.verified_model is fabricated  # deliberate forgery: in-model for
        # review, out of scope for the type system (#314 design ruling).

    def test_dataclasses_replace_on_token_cannot_relabel_it_remote(self) -> None:
        # Forge attempt (test-design, #278): dataclasses.replace re-runs __init__ /
        # __post_init__ with the InitVar mint key at its default (None), so mutating
        # a genuine local token's model_id to a remote one FAILS the mint check --
        # replace cannot launder a verified local token into a remote one.
        token = _local_token("ollama/my-model")
        with pytest.raises(ComparabilityError, match="only be minted by the"):
            dataclasses.replace(token, model_id="openai/gpt-4o")
        # Even explicitly re-passing the (guessed) default key is refused.
        with pytest.raises(ComparabilityError, match="only be minted by the"):
            dataclasses.replace(token, model_id="openai/gpt-4o", _mint_key=None)

    def test_dataclasses_replace_on_row_cannot_swap_in_a_remote_model(self) -> None:
        # Forge attempt (test-design, #278): take a valid Tier-A row and try to
        # dataclasses.replace its model_id to a remote one while keeping the (local)
        # token. replace re-runs ComparisonRow.__post_init__, so the token/model_id
        # mismatch check fires -- a row cannot be relabeled onto a model its token
        # does not attest.
        good = ComparisonRow(
            scenario_id="tier4_bug_fix",
            battery_run_id="b",
            harness="opencode",
            model_id="ollama/my-model",
            tier=TIER_A_FIXED_LOCAL,
            repeat_idx=0,
            session_id="s",
            outcome="success",
            metrics={},
            verified_model=_local_token("ollama/my-model"),
        )
        with pytest.raises(ComparabilityError, match="attests"):
            dataclasses.replace(good, model_id="openai/gpt-4o")

    def test_comparison_row_tier_b_allows_empty_model_id(self) -> None:
        row = ComparisonRow(
            scenario_id="tier4_bug_fix",
            battery_run_id="b",
            harness="claude-code",
            model_id="",
            tier=TIER_B_NATIVE,
            repeat_idx=0,
            session_id="s",
            outcome="success",
            metrics={},
        )
        assert row.tier == TIER_B_NATIVE and row.model_id == ""

    def test_runner_rejects_tier_a_non_gated_harness(self, tmp_path: Path) -> None:
        # #273/#278 facet 2, end-to-end: a Tier-A leg on a harness that cannot pin
        # the local model reaches row construction with no token and fails closed --
        # nothing persisted.
        stub = StubSandbox(_result())
        db = _NoWriteDB()
        runner = _runner(stub, db, repeats=1)
        with pytest.raises(ComparabilityError, match="no gate-verified local model"):
            runner.run(
                ["tier4_bug_fix"],
                [HarnessLeg("claude-code", tier=TIER_A_FIXED_LOCAL)],
                battery_run_id="batt-bypass",
            )
        assert db.saved == []  # no half-written spine row

    def test_runner_rejects_remote_opencode_model_override(
        self, tmp_path: Path
    ) -> None:
        # --opencode-model must not smuggle a remote model into a Tier-A row past
        # the config gate: the override itself is resolved local, and fails first.
        stub = StubSandbox(_result())
        db = _NoWriteDB()
        runner = _runner(stub, db, repeats=1)
        with pytest.raises(ComparabilityError, match="not declared"):
            runner.run(
                ["tier4_bug_fix"],
                [
                    HarnessLeg(
                        "opencode", model="openai/gpt-4o", tier=TIER_A_FIXED_LOCAL
                    )
                ],
                battery_run_id="batt-override",
            )
        assert stub.calls == []  # rejected before any scenario ran
        assert db.saved == []

    def test_runner_bad_config_writes_no_spine_row(self, tmp_path: Path) -> None:
        # The #273 end-to-end claim reversed: a frontier config yields NO spine row.
        bad = _write_cfg(tmp_path, {"model": "openai/gpt-4o"})
        stub = StubSandbox(_result())
        db = _NoWriteDB()
        runner = _runner(stub, db, repeats=1, opencode_config=bad)
        with pytest.raises(ComparabilityError, match="not declared"):
            runner.run(["tier4_bug_fix"], [HarnessLeg("opencode")], battery_run_id="b")
        assert stub.calls == []  # gate blocks before any run
        assert db.saved == []
