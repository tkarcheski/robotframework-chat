"""Unit tests for the tier:4 Docker sandbox harness (rfc.agent_sandbox).

The sandbox itself talks to Docker through the ContainerManager interface;
these tests inject a fake manager so the harness logic (scenario loading,
manifest diffing, churn detection, AgentRun assembly, cleanup) is verified
hermetically. The real-Docker path is exercised by
robot/agentic_coding/tests/test_sandboxed.robot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfc.agent_config import SandboxLimits
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
        text = "aa11  /workspace/calculator.py\nbb22  /workspace/tests/test_x.py\n"
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
    text = "".join(f"{h}  /workspace/{p}\n" for p, h in entries.items())
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
