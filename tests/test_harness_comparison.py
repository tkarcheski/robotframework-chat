"""Deterministic twin for RFC-007 S2 comparison mode (#218).

Exercises the whole metric-writing path against hermetic sqlite with no models,
no Docker, and no tokens: a stub sandbox for the combinatorial pairing/tier/skip
cases, and one faithful end-to-end run through the real ``AgentSandbox`` live
path (fake container manager + replayed transcript).
"""

from __future__ import annotations

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
        # Live path exec order: baseline manifest, workspace clear, after
        # manifest, tests -- the opencode transcript fixes calculator.py green.
        fake = _FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old", "test_calculator.py": "t"}),
                {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 1},
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
    def test_comparison_row_tier_a_requires_model_id(self) -> None:
        # #273 facet 2, at the type: a Tier-A row with empty model_id cannot exist.
        with pytest.raises(ComparabilityError, match="empty model_id"):
            ComparisonRow(
                scenario_id="tier4_bug_fix",
                battery_run_id="b",
                harness="claude-code",
                model_id="",
                tier=TIER_A_FIXED_LOCAL,
                repeat_idx=0,
                session_id="s",
                outcome="success",
                metrics={},
            )

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
        # #273 facet 2, end-to-end: a Tier-A leg on a harness that cannot pin the
        # local model reaches row construction and fails closed -- nothing persisted.
        stub = StubSandbox(_result())
        db = _NoWriteDB()
        runner = _runner(stub, db, repeats=1)
        with pytest.raises(ComparabilityError, match="empty model_id"):
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
