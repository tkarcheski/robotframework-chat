"""Unit tests for the tier:4 Docker sandbox harness (rfc.agent_sandbox).

The sandbox itself talks to Docker through the ContainerManager interface;
these tests inject a fake manager so the harness logic (scenario loading,
manifest diffing, churn detection, AgentRun assembly, cleanup) is verified
hermetically. The real-Docker path is exercised by
robot/40__tier4/agentic_coding/tests/test_sandboxed.robot.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from rfc.agent_config import SandboxLimits
from rfc.exceptions import HarnessNotAvailableError, LiveHarnessNotRoutedError
from rfc.harness_adapters import ClaudeProcessResult, CodexAdapter, OpenCodeAdapter
from rfc.opencode_config import _DEFAULT_OPENCODE_CONFIG
from rfc.agent_sandbox import (
    DEFAULT_SANDBOX_SCENARIOS_ROOT,
    AgentSandbox,
    SandboxResult,
    diff_manifests,
    filter_unexpected,
    load_sandbox_scenario,
    parse_manifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Fixtures shipped with the suite
# ---------------------------------------------------------------------------


class TestShippedScenarios:
    """The two starter scenarios from #290 must be loadable and well-formed."""

    @pytest.mark.parametrize("scenario_id", ["tier4_bug_fix", "tier4_regression_guard"])
    def test_scenario_loads(self, scenario_id: str) -> None:
        scenario = load_sandbox_scenario(DEFAULT_SANDBOX_SCENARIOS_ROOT / scenario_id)
        assert scenario.scenario_id == scenario_id
        assert scenario.task
        assert scenario.test_command
        assert scenario.allowed_paths
        assert scenario.agents

    def test_bug_fix_has_good_and_churn_variants(self) -> None:
        scenario = load_sandbox_scenario(
            DEFAULT_SANDBOX_SCENARIOS_ROOT / "tier4_bug_fix"
        )
        assert set(scenario.agents) >= {"good", "churn"}
        for variant in scenario.agents:
            assert scenario.agent_script(variant).is_file()

    def test_regression_guard_has_careful_and_naive_variants(self) -> None:
        scenario = load_sandbox_scenario(
            DEFAULT_SANDBOX_SCENARIOS_ROOT / "tier4_regression_guard"
        )
        assert set(scenario.agents) >= {"careful", "naive"}

    @pytest.mark.parametrize("scenario_id", ["tier4_bug_fix", "tier4_regression_guard"])
    def test_scenario_repo_contains_a_unittest_file(self, scenario_id: str) -> None:
        repo = DEFAULT_SANDBOX_SCENARIOS_ROOT / scenario_id / "repo"
        assert repo.is_dir()
        assert list(repo.glob("test_*.py")), "scenario repo must ship its tests"


class TestLoadSandboxScenario:
    def _write_minimal(self, root: Path) -> Path:
        scenario_dir = root / "demo"
        (scenario_dir / "repo").mkdir(parents=True)
        (scenario_dir / "repo" / "mod.py").write_text("X = 1\n")
        (scenario_dir / "agents").mkdir()
        (scenario_dir / "agents" / "good.sh").write_text("true\n")
        (scenario_dir / "scenario.yaml").write_text(
            "scenario_id: demo\n"
            "task: fix it\n"
            "test_command: python -m unittest discover -v\n"
            "allowed_paths:\n  - mod.py\n"
            "agents:\n  good: agents/good.sh\n"
        )
        return scenario_dir

    def test_load_roundtrip(self, tmp_path: Path) -> None:
        scenario = load_sandbox_scenario(self._write_minimal(tmp_path))
        assert scenario.scenario_id == "demo"
        assert scenario.allowed_paths == ("mod.py",)
        assert scenario.agent_script("good").name == "good.sh"

    def test_missing_repo_dir_raises(self, tmp_path: Path) -> None:
        scenario_dir = self._write_minimal(tmp_path)
        (scenario_dir / "repo" / "mod.py").unlink()
        (scenario_dir / "repo").rmdir()
        with pytest.raises(ValueError, match="repo"):
            load_sandbox_scenario(scenario_dir)

    def test_missing_agent_script_raises(self, tmp_path: Path) -> None:
        scenario_dir = self._write_minimal(tmp_path)
        (scenario_dir / "agents" / "good.sh").unlink()
        with pytest.raises(ValueError, match="good"):
            load_sandbox_scenario(scenario_dir)

    def test_unknown_variant_raises_keyerror(self, tmp_path: Path) -> None:
        scenario = load_sandbox_scenario(self._write_minimal(tmp_path))
        with pytest.raises(KeyError, match="nope"):
            scenario.agent_script("nope")

    def test_missing_required_key_raises(self, tmp_path: Path) -> None:
        scenario_dir = self._write_minimal(tmp_path)
        (scenario_dir / "scenario.yaml").write_text("scenario_id: demo\n")
        with pytest.raises(ValueError, match="task"):
            load_sandbox_scenario(scenario_dir)


# ---------------------------------------------------------------------------
# Pure manifest helpers
# ---------------------------------------------------------------------------


class TestManifestHelpers:
    def test_parse_manifest_strips_workspace_prefix(self) -> None:
        text = "aa11  /workspace/calculator.py\0bb22  /workspace/tests/test_x.py\0"
        assert parse_manifest(text) == {
            "calculator.py": "aa11",
            "tests/test_x.py": "bb22",
        }

    def test_parse_manifest_ignores_blank_lines(self) -> None:
        assert parse_manifest("\n\n") == {}

    def test_diff_manifests_detects_modified_added_removed(self) -> None:
        before = {"a.py": "1", "b.py": "2", "c.py": "3"}
        after = {"a.py": "1", "b.py": "CHANGED", "d.py": "4"}
        assert diff_manifests(before, after) == ("b.py", "c.py", "d.py")

    def test_diff_manifests_identical_is_empty(self) -> None:
        manifest = {"a.py": "1"}
        assert diff_manifests(manifest, dict(manifest)) == ()

    def test_filter_unexpected_allows_exact_and_prefix(self) -> None:
        changed = ("calculator.py", "notes.txt", "src/extra.py")
        assert filter_unexpected(changed, ("calculator.py", "src/")) == ("notes.txt",)

    def test_filter_unexpected_empty_allowed_flags_everything(self) -> None:
        assert filter_unexpected(("x",), ()) == ("x",)


# ---------------------------------------------------------------------------
# AgentSandbox against a fake container manager
# ---------------------------------------------------------------------------


class FakeContainerManager:
    """Scripted stand-in for rfc.container_manager.ContainerManager."""

    def __init__(self, exec_results: list[dict] | None = None) -> None:
        self.exec_results = list(exec_results or [])
        self.exec_calls: list[dict] = []
        self.copy_calls: list[tuple[str, str, str]] = []
        self.created: list[object] = []
        self.stopped: list[str] = []

    def create_container(self, config, name=None) -> str:
        self.created.append(config)
        return "cid-1234567890"

    def execute_command(self, container_id, command, timeout=30, workdir=None):
        self.exec_calls.append(
            {"command": command, "timeout": timeout, "workdir": workdir}
        )
        if self.exec_results:
            return self.exec_results.pop(0)
        return {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 1}

    def copy_to_container(self, container_id, host_path, container_path) -> None:
        self.copy_calls.append((container_id, str(host_path), container_path))

    def stop_container(self, container_id, timeout=10) -> None:
        self.stopped.append(container_id)


def _limits(**overrides) -> SandboxLimits:
    defaults = dict(
        image="python:3.11-slim",
        cpu_cores=1.0,
        memory_mb=512,
        wall_clock_seconds=42,
        network_mode="none",
    )
    defaults.update(overrides)
    return SandboxLimits(**defaults)


def _manifest(entries: dict[str, str]) -> dict:
    text = "".join(f"{h}  /workspace/{p}\0" for p, h in entries.items())
    return {"stdout": text, "stderr": "", "exit_code": 0, "duration_ms": 1}


BUG_FIX_DIR = DEFAULT_SANDBOX_SCENARIOS_ROOT / "tier4_bug_fix"


class TestAgentSandboxRun:
    def _run(self, fake: FakeContainerManager) -> SandboxResult:
        sandbox = AgentSandbox(limits=_limits(), manager=fake)
        return sandbox.run_scenario(BUG_FIX_DIR, variant="good", agent_id="claude-code")

    def test_happy_path_result(self) -> None:
        fake = FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old", "test_calculator.py": "t"}),
                {"stdout": "fixed", "stderr": "", "exit_code": 0, "duration_ms": 5},
                _manifest({"calculator.py": "new", "test_calculator.py": "t"}),
                {"stdout": "OK", "stderr": "", "exit_code": 0, "duration_ms": 9},
            ]
        )
        result = self._run(fake)
        assert result.agent_exit_code == 0
        assert result.tests_exit_code == 0
        assert result.tests_passed
        assert result.changed_paths == ("calculator.py",)
        assert result.unexpected_paths == ()
        assert not result.has_unexpected_churn

    def test_unexpected_churn_is_flagged(self) -> None:
        fake = FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old"}),
                {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 5},
                _manifest({"calculator.py": "new", "debug.log": "junk"}),
                {"stdout": "OK", "stderr": "", "exit_code": 0, "duration_ms": 9},
            ]
        )
        result = self._run(fake)
        assert result.unexpected_paths == ("debug.log",)
        assert result.has_unexpected_churn

    def test_failing_tests_surface_in_result(self) -> None:
        fake = FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old"}),
                {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 5},
                _manifest({"calculator.py": "new"}),
                {"stdout": "FAILED", "stderr": "", "exit_code": 1, "duration_ms": 9},
            ]
        )
        result = self._run(fake)
        assert result.tests_exit_code == 1
        assert not result.tests_passed

    def test_default_result_has_no_timeout_flags(self) -> None:
        # #251: a clean scripted run flags neither timeout.
        fake = FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old"}),
                {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 5},
                _manifest({"calculator.py": "new"}),
                {"stdout": "OK", "stderr": "", "exit_code": 0, "duration_ms": 9},
            ]
        )
        result = self._run(fake)
        assert result.timed_out is False
        assert result.tests_timed_out is False

    def test_scripted_agent_timeout_sets_timed_out(self) -> None:
        # #251: the container `timeout` wrapper emits 124 when the agent
        # overruns; the sandbox is the single point of truth that turns that
        # into timed_out=True. tests still complete, so tests_timed_out=False.
        fake = FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old"}),
                {"stdout": "", "stderr": "", "exit_code": 124, "duration_ms": 5},
                _manifest({"calculator.py": "old"}),
                {"stdout": "FAILED", "stderr": "", "exit_code": 1, "duration_ms": 9},
            ]
        )
        result = self._run(fake)
        assert result.agent_exit_code == 124
        assert result.timed_out is True
        assert result.tests_timed_out is False

    def test_scripted_tests_timeout_sets_tests_timed_out(self) -> None:
        # #251: a 124 from the verification command is a distinct outcome
        # (tests_timed_out) from an agent timeout -- both were previously 124.
        fake = FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old"}),
                {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 5},
                _manifest({"calculator.py": "new"}),
                {"stdout": "", "stderr": "", "exit_code": 124, "duration_ms": 9},
            ]
        )
        result = self._run(fake)
        assert result.tests_exit_code == 124
        assert result.tests_timed_out is True
        assert result.timed_out is False

    def test_agent_command_is_wall_clock_capped_with_kill_escalation(self) -> None:
        """PR #490 review (P1): plain `timeout` only sends SIGTERM; an agent
        (or child) that ignores it survives the advertised wall-clock cap.
        `--kill-after` escalates to SIGKILL so the limit is actually enforced.
        """
        fake = FakeContainerManager()
        self._run(fake)
        agent_call = fake.exec_calls[1]
        assert agent_call["command"].startswith("timeout -k 10s 42s ")
        assert agent_call["workdir"] == "/workspace"

    def test_test_command_is_wall_clock_capped_with_kill_escalation(self) -> None:
        fake = FakeContainerManager()
        self._run(fake)
        test_call = fake.exec_calls[3]
        assert test_call["command"].startswith("timeout -k 10s 42s ")
        assert test_call["workdir"] == "/workspace"

    def test_container_is_stopped_on_success(self) -> None:
        fake = FakeContainerManager()
        self._run(fake)
        assert fake.stopped == ["cid-1234567890"]

    def test_container_is_stopped_when_exec_raises(self) -> None:
        class ExplodingManager(FakeContainerManager):
            def execute_command(self, *args, **kwargs):
                raise RuntimeError("boom")

        fake = ExplodingManager()
        sandbox = AgentSandbox(limits=_limits(), manager=fake)
        with pytest.raises(RuntimeError, match="boom"):
            sandbox.run_scenario(BUG_FIX_DIR, variant="good", agent_id="claude-code")
        assert fake.stopped == ["cid-1234567890"]

    def test_repo_and_agent_script_are_copied_in(self) -> None:
        fake = FakeContainerManager()
        self._run(fake)
        host_paths = [c[1] for c in fake.copy_calls]
        assert str(BUG_FIX_DIR / "repo") in host_paths[0]
        assert host_paths[1].endswith("good.sh")

    def test_container_config_applies_limits(self) -> None:
        fake = FakeContainerManager()
        sandbox = AgentSandbox(
            limits=_limits(cpu_cores=0.5, memory_mb=256), manager=fake
        )
        sandbox.run_scenario(BUG_FIX_DIR, variant="good", agent_id="claude-code")
        config = fake.created[0]
        assert config.image == "python:3.11-slim"
        assert config.resources.memory_mb == 256
        assert config.resources.cpu_quota == 50000
        assert config.network.mode == "none"

    def test_agent_run_is_normalized(self) -> None:
        fake = FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old"}),
                {"stdout": "did it", "stderr": "", "exit_code": 0, "duration_ms": 5},
                _manifest({"calculator.py": "new"}),
                {"stdout": "OK", "stderr": "", "exit_code": 0, "duration_ms": 9},
            ]
        )
        result = self._run(fake)
        run = result.run
        assert run.agent_id == "claude-code"
        assert run.scenario_id == "tier4_bug_fix"
        assert run.base_branch == "claude-code-staging"
        assert len(run.commands) == 2
        assert run.commands[0].changed_paths_after == ("calculator.py",)
        assert run.commands[1].returncode == 0

    def test_scenario_resolved_by_id_string(self) -> None:
        fake = FakeContainerManager()
        sandbox = AgentSandbox(limits=_limits(), manager=fake)
        result = sandbox.run_scenario(
            "tier4_bug_fix", variant="good", agent_id="claude-code"
        )
        assert result.scenario_id == "tier4_bug_fix"


# ---------------------------------------------------------------------------
# Live harness path (#174): the agent runs on the HOST, the container verifies.
# Deterministic — an injected invoker replays a recorded transcript (no CLI)
# and a fake container manager stands in for Docker.
# ---------------------------------------------------------------------------

# opencode ``run --format json`` event: one completed bash tool call fixing the
# subtract bug. parse_opencode_events turns it into a single AgentCommand.
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


def _recording_invoker(stdout: str = "", returncode: int = 0, calls=None):
    """A ProcessInvoker double that records its calls and replays ``stdout``."""

    def invoker(argv, cwd, env, timeout):
        if calls is not None:
            calls.append(
                {
                    "argv": tuple(argv),
                    "cwd": Path(cwd),
                    "env": dict(env),
                    "timeout": timeout,
                }
            )
        return ClaudeProcessResult(returncode=returncode, stdout=stdout, stderr="")

    return invoker


def _opencode_routing_invoker(samples: list[float], calls: list[dict] | None = None):
    """An opencode invoker double that plays the rfc-exec MCP child (#381).

    opencode consumes a config FILE (``OPENCODE_CONFIG``), not inline argv, so
    this reads the merged routed config the sandbox exported, pulls the broker's
    metrics-sink path out of its ``mcp`` block (exactly where the sandbox threaded
    it), and writes ``samples`` there -- standing in for the broker having
    dispatched that many code-exec calls into the container. Returns opencode's
    JSON event stream fixing the seeded bug.
    """

    def invoker(argv, cwd, env, timeout):
        config_path = env.get("OPENCODE_CONFIG")
        cfg = None
        if config_path:
            # Capture the merged routed config NOW (it lives in the run's temp dir,
            # torn down when the run ends), and write broker overhead samples to
            # the metrics sink named in its mcp block.
            cfg = json.loads(Path(config_path).read_text())
            env_block = cfg["mcp"]["rfc-exec"]["environment"]
            metrics_path = env_block.get("RFC_EXEC_METRICS_PATH")
            if metrics_path:
                Path(metrics_path).write_text("".join(f"{s}\n" for s in samples))
        if calls is not None:
            calls.append(
                {"argv": tuple(argv), "cwd": Path(cwd), "env": dict(env), "config": cfg}
            )
        return ClaudeProcessResult(
            returncode=0, stdout=OPENCODE_FIX_TRANSCRIPT, stderr=""
        )

    return invoker


class TestAgentSandboxLiveHarness:
    """The live-harness dispatch. Routed harnesses (claude-code #235, opencode
    #381) run host-side and verify against the container their code-exec routed
    into; a still-non-routed harness (codex -- CLI absent, exec un-routed) FAILS
    CLOSED rather than be verified against a ``/workspace`` its edits never
    reached (#377)."""

    def _verify_manager(self, after_entries: dict[str, str]) -> FakeContainerManager:
        # exec order (#235): baseline manifest, after manifest, tests. A ROUTED
        # harness mutates /workspace in place via the broker, so there is no
        # host-side copy-back / workspace-clear step -- the container is manifested
        # in place before and after the agent runs. Scripting ``after`` is only
        # honest for a routed harness (whose edits actually reach the container).
        return FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old", "test_calculator.py": "t"}),
                _manifest(after_entries),
                {"stdout": "OK", "stderr": "", "exit_code": 0, "duration_ms": 9},
            ]
        )

    # -- opencode: the #377 fail-closed test, FLIPPED to a routed happy path (#381)

    def test_routed_opencode_writes_correct_result_into_container(self) -> None:
        # #381 flips the exact test that caught #377. opencode now ROUTES its
        # per-tool-call code-exec into /workspace via the rfc-exec broker, so it
        # is honestly container-verified in place (the inverse of the fail-closed
        # this test used to assert). A container IS created and verified; the fix
        # reads as fixed; per-call broker overhead is carried on the result; and
        # the exported routed config denies opencode's native code tools and binds
        # the rfc-exec server to THIS run's container.
        calls: list[dict] = []
        fake = self._verify_manager({"calculator.py": "new", "test_calculator.py": "t"})
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_opencode_routing_invoker([12.0, 19.0], calls=calls),
        )
        result = sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="opencode",
            agent_id="opencode",
            harness="opencode",
        )
        # A container WAS created and verified in place (no fail-closed skip): the
        # three exec calls are baseline manifest, after manifest, and tests.
        assert len(fake.created) == 1
        assert len(fake.exec_calls) == 3
        assert result.tests_passed
        assert result.changed_paths == ("calculator.py",)
        assert not result.has_unexpected_churn
        # Per-call broker overhead surfaced -- the Tier-A cost tier is populated,
        # not just task-success.
        assert result.sandbox_exec_overhead_ms == (12.0, 19.0)
        # Config-level conformance: the merged routed config the sandbox exported
        # denies opencode's native code tools (permission + tools layers) and
        # registers the rfc-exec server bound to this run's container id. Captured
        # by the invoker while the run's temp config still existed.
        cfg = calls[0]["config"]
        assert cfg["permission"]["bash"] == "deny"
        assert cfg["permission"]["write"] == "deny"
        assert cfg["tools"]["bash"] is False
        assert (
            cfg["mcp"]["rfc-exec"]["environment"]["RFC_EXEC_CONTAINER_ID"]
            == "cid-1234567890"
        )
        # The pinned local model survived the overlay merge (Tier-A comparability).
        assert cfg["model"]

    def test_nonrouted_codex_fails_closed_even_with_cli_present(self) -> None:
        # An injected invoker disarms the probe gate (as if codex were installed),
        # so this isolates the ROUTING check from mere CLI availability: a present
        # but un-routed harness must still fail closed.
        fake = FakeContainerManager()
        sandbox = AgentSandbox(
            limits=_limits(), manager=fake, invoker=_recording_invoker()
        )
        with pytest.raises(LiveHarnessNotRoutedError):
            sandbox.run_scenario(
                BUG_FIX_DIR, variant="codex", agent_id="codex", harness="codex"
            )
        assert fake.created == []

    def test_wire_exec_routing_arms_opencode(self, tmp_path: Path) -> None:
        # #381: opencode is now a routed harness, so _wire_exec_routing arms its
        # exec_routing AND materializes a merged routed config (base opencode.json
        # + deny overlay + rfc-exec server) that env_overrides exports as
        # OPENCODE_CONFIG -- the mechanism that actually substitutes its native
        # code tools for the broker'd ones.
        sandbox = AgentSandbox(limits=_limits(), manager=FakeContainerManager())
        adapter = OpenCodeAdapter(config_path=_DEFAULT_OPENCODE_CONFIG)
        sandbox._wire_exec_routing(adapter, "cid-1", tmp_path / "overhead.jsonl")
        assert adapter.exec_routing is not None
        assert adapter.exec_routing.container_id == "cid-1"
        env = adapter.env_overrides()
        cfg = json.loads(Path(env["OPENCODE_CONFIG"]).read_text())
        assert cfg["permission"]["bash"] == "deny"
        assert cfg["mcp"]["rfc-exec"]["environment"]["RFC_EXEC_CONTAINER_ID"] == "cid-1"

    def test_wire_exec_routing_leaves_codex_host_native(self) -> None:
        # codex is NOT in the routed set (CLI absent, exec un-routed), so
        # _wire_exec_routing is a no-op for it -- and the live run fails it closed
        # before any container exists rather than verifying against a pristine
        # /workspace its edits never reached. The guard stays as defence in depth.
        sandbox = AgentSandbox(limits=_limits(), manager=FakeContainerManager())
        adapter = CodexAdapter()
        sandbox._wire_exec_routing(adapter, "cid-1", Path("/tmp/overhead.jsonl"))
        assert getattr(adapter, "exec_routing", None) is None

    # -- routed happy-path + harness-agnostic live mechanics (claude-code) ------

    def test_live_routed_harness_runs_head_on_host_not_in_container(self) -> None:
        calls: list[dict] = []
        fake = self._verify_manager({"calculator.py": "new", "test_calculator.py": "t"})
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_recording_invoker(stdout=CLAUDE_MCP_FIX_TRANSCRIPT, calls=calls),
        )
        sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="claude-code",
            agent_id="claude-code",
            harness="claude-code",
        )
        # The agent CLI (the head) ran exactly once, host-side, via the injected
        # invoker, in a throwaway host CWD stub (not inside the container).
        assert len(calls) == 1
        assert calls[0]["argv"][0] == "claude"
        assert calls[0]["cwd"].name == "workspace"
        assert calls[0]["timeout"] == _limits().wall_clock_seconds
        # The container is seeded ONCE from the pristine repo (#235: no host-side
        # copy-back), and the three exec calls are baseline manifest, after
        # manifest, and tests -- never an agent script into /tmp.
        assert {c[2] for c in fake.copy_calls} == {"/workspace"}
        assert len(fake.copy_calls) == 1
        assert len(fake.exec_calls) == 3

    def test_live_routed_harness_captures_trajectory_and_test_row(self) -> None:
        fake = self._verify_manager({"calculator.py": "new", "test_calculator.py": "t"})
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_recording_invoker(stdout=CLAUDE_MCP_FIX_TRANSCRIPT),
        )
        run = sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="claude-code",
            agent_id="claude-code",
            harness="claude-code",
        ).run
        assert run.agent_id == "claude-code"
        assert run.scenario_id == "tier4_bug_fix"
        # parsed agent trajectory + the verification test row.
        assert len(run.commands) == 2
        assert run.commands[0].argv == (
            "bash",
            "-lc",
            "sed -i 's/a + b/a - b/' calculator.py",
        )
        assert run.commands[-1].argv[:2] == ("sh", "-c")
        assert run.commands[-1].changed_paths_after == ("calculator.py",)

    def test_live_routed_harness_unexpected_churn_is_flagged(self) -> None:
        fake = self._verify_manager(
            {"calculator.py": "new", "test_calculator.py": "t", "debug.log": "junk"}
        )
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_recording_invoker(stdout=CLAUDE_MCP_FIX_TRANSCRIPT),
        )
        result = sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="claude-code",
            agent_id="claude-code",
            harness="claude-code",
        )
        assert result.unexpected_paths == ("debug.log",)
        assert result.has_unexpected_churn

    def test_absent_harness_cli_skips_cleanly(self) -> None:
        # No invoker injected -> probe gate is armed. This exercises the
        # CLI-absent fail-closed path, so pin the codex probe to "absent" rather
        # than assuming codex is uninstalled: fleet boxes wiring codex (#378) DO
        # have it on PATH, where a live probe passes and the run instead hits the
        # not-routed guard (LiveHarnessNotRoutedError), masking this contract.
        fake = FakeContainerManager()
        sandbox = AgentSandbox(limits=_limits(), manager=fake)
        with (
            patch.object(CodexAdapter, "probe", return_value=False),
            pytest.raises(HarnessNotAvailableError),
        ):
            sandbox.run_scenario(
                BUG_FIX_DIR, variant="codex", agent_id="codex", harness="codex"
            )
        assert fake.created == []
        assert fake.exec_calls == []

    def test_live_routed_harness_wall_clock_timeout_yields_bounded_result(self) -> None:
        # A live agent that overruns the cap must degrade to exit 124 + a
        # verified (red) result, not crash the harness. The container still
        # verifies whatever partial state the agent left behind.
        fake = self._verify_manager({"calculator.py": "old", "test_calculator.py": "t"})
        fake.exec_results[-1] = {
            "stdout": "FAILED",
            "stderr": "",
            "exit_code": 1,
            "duration_ms": 9,
        }

        def timing_out_invoker(argv, cwd, env, timeout):
            raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout, output="")

        sandbox = AgentSandbox(
            limits=_limits(), manager=fake, invoker=timing_out_invoker
        )
        result = sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="claude-code",
            agent_id="claude-code",
            harness="claude-code",
        )
        assert result.agent_exit_code == 124
        assert result.timed_out is True
        # #251: the tests still ran to completion (red), so tests_timed_out
        # stays False -- an agent timeout and a test timeout are distinct.
        assert result.tests_timed_out is False
        assert not result.tests_passed
        # verification still ran against the partial workspace.
        assert len(fake.exec_calls) == 3

    def test_live_cli_exit_124_is_not_flagged_as_timeout(self) -> None:
        # #251 conflation fix: a live CLI that itself exits 124 on the happy
        # path (no TimeoutExpired) is NOT a harness kill. agent_exit_code is
        # preserved as 124, but timed_out is False -- the flag is set only
        # where the timeout actually fires, so a scoreboard never inflates
        # the timeout rate with an agent-chosen 124.
        fake = self._verify_manager({"calculator.py": "new", "test_calculator.py": "t"})
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_recording_invoker(
                stdout=CLAUDE_MCP_FIX_TRANSCRIPT, returncode=124
            ),
        )
        result = sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="claude-code",
            agent_id="claude-code",
            harness="claude-code",
        )
        assert result.agent_exit_code == 124
        assert result.timed_out is False

    def test_unknown_harness_name_raises_keyerror(self) -> None:
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=FakeContainerManager(),
            invoker=_recording_invoker(),
        )
        with pytest.raises(KeyError, match="nope"):
            sandbox.run_scenario(
                BUG_FIX_DIR, variant="nope", agent_id="nope", harness="nope"
            )


# claude-code stream-json: one container-routed mcp__rfc-exec__bash tool call
# that fixes the subtract bug, paired with its tool_result.
CLAUDE_MCP_FIX_TRANSCRIPT = (
    json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "mcp__rfc-exec__bash",
                        "input": {"command": "sed -i 's/a + b/a - b/' calculator.py"},
                    }
                ]
            },
        }
    )
    + "\n"
    + json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu1",
                        "content": [{"type": "text", "text": "done"}],
                        "is_error": False,
                    }
                ]
            },
        }
    )
    + "\n"
)


def _claude_routing_invoker(samples: list[float], calls: list[dict] | None = None):
    """A claude-code invoker double that plays the rfc-exec MCP child.

    It reads the metrics-sink path out of the ``--mcp-config`` env block (exactly
    where the sandbox threads it) and writes ``samples`` there, standing in for
    the broker having dispatched that many code-exec calls into the container.
    """

    def invoker(argv, cwd, env, timeout):
        argv_list = list(argv)
        if calls is not None:
            calls.append({"argv": tuple(argv_list), "cwd": Path(cwd)})
        mcp_json = argv_list[argv_list.index("--mcp-config") + 1]
        env_block = json.loads(mcp_json)["mcpServers"]["rfc-exec"]["env"]
        metrics_path = env_block.get("RFC_EXEC_METRICS_PATH")
        if metrics_path:
            Path(metrics_path).write_text("".join(f"{s}\n" for s in samples))
        return ClaudeProcessResult(
            returncode=0, stdout=CLAUDE_MCP_FIX_TRANSCRIPT, stderr=""
        )

    return invoker


class TestAgentSandboxLiveExecRouting:
    """#235: claude-code's code-exec routes into the pre-warmed container."""

    def _verify_manager(self, after_entries: dict[str, str]) -> FakeContainerManager:
        return FakeContainerManager(
            exec_results=[
                _manifest({"calculator.py": "old", "test_calculator.py": "t"}),
                _manifest(after_entries),
                {"stdout": "OK", "stderr": "", "exit_code": 0, "duration_ms": 9},
            ]
        )

    def test_routing_threaded_and_overhead_recorded(self) -> None:
        calls: list[dict] = []
        fake = self._verify_manager({"calculator.py": "new", "test_calculator.py": "t"})
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_claude_routing_invoker([15.0, 22.0], calls=calls),
        )
        result = sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="claude-code",
            agent_id="claude-code",
            harness="claude-code",
        )
        # Deny-settings strip the native code tools; the mcp-config binds the
        # rfc-exec server to THIS run's pre-warmed container id.
        argv = list(calls[0]["argv"])
        deny = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
        assert "Bash" in deny
        mcp = json.loads(argv[argv.index("--mcp-config") + 1])
        assert (
            mcp["mcpServers"]["rfc-exec"]["env"]["RFC_EXEC_CONTAINER_ID"]
            == "cid-1234567890"
        )
        # The routed mcp__rfc-exec__bash command populated the trajectory (else
        # remoted calls silently vanish from the AgentRun).
        assert result.run.commands[0].argv == (
            "bash",
            "-lc",
            "sed -i 's/a + b/a - b/' calculator.py",
        )
        # Per-call overhead samples surfaced from the broker's metrics sink.
        assert result.sandbox_exec_overhead_ms == (15.0, 22.0)
        assert result.tests_passed
        assert result.changed_paths == ("calculator.py",)

    def test_no_samples_when_broker_not_exercised(self) -> None:
        # An injected invoker that writes no samples leaves the overhead tuple
        # empty and the (vacuous) budget met -- no false measurement.
        fake = self._verify_manager({"calculator.py": "new", "test_calculator.py": "t"})
        sandbox = AgentSandbox(
            limits=_limits(),
            manager=fake,
            invoker=_claude_routing_invoker([]),
        )
        result = sandbox.run_scenario(
            BUG_FIX_DIR,
            variant="claude-code",
            agent_id="claude-code",
            harness="claude-code",
        )
        assert result.sandbox_exec_overhead_ms == ()
