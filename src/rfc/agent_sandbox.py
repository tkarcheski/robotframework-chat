"""Docker-sandboxed execution harness for the agentic-coding suite (tier:4).

Spins up a disposable container, seeds it with a scenario repo, runs an agent
command inside it under resource caps, then verifies the resulting worktree
state: the scenario's tests still pass and no unexpected file churn occurred.

The agent side is deliberately pluggable. Today each scenario ships scripted
agent variants (``agents/*.sh``) that stand in for a live coding agent; when
the live Claude Code adapter lands (#288, ``LiveClaudeCodeRunner``), it plugs
into the same entry point by producing the command executed inside the
container. Every run is normalized into the same :class:`~rfc.agent_run.AgentRun`
the rest of the suite's verifiers consume.

Scenario fixture layout::

    robot/tier4/agentic_coding/fixtures/sandbox/
      <scenario_id>/
        scenario.yaml      # task, test_command, allowed_paths, agent variants
        repo/              # disposable repo seeded into the container
        agents/<name>.sh   # scripted agent variants (live adapter follow-up)

Docker unavailability raises :class:`~rfc.exceptions.DockerNotAvailableError`
(``ROBOT_SKIP_EXECUTION``), so Robot tests skip cleanly without a daemon.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol

import yaml
from robot.api import logger

from rfc.agent_config import SandboxLimits
from rfc.agent_run import AgentCommand, AgentRun

DEFAULT_SANDBOX_SCENARIOS_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "robot"
    / "tier4"
    / "agentic_coding"
    / "fixtures"
    / "sandbox"
)

_WORKSPACE = "/workspace"
_AGENT_SCRIPT_DIR = "/tmp"
_MANIFEST_COMMAND = (
    f"find {_WORKSPACE} -type f -not -path '*/.git/*' -exec sha256sum {{}} + | sort"
)
_OUTPUT_TAIL_CHARS = 4000
# Grace period between SIGTERM and SIGKILL for `timeout -k`. Without the
# escalation, an agent (or child) that ignores SIGTERM outlives the
# advertised wall-clock cap and can hang the suite (PR #490 review, P1).
_KILL_AFTER_SECONDS = 10
_SANDBOX_BASE_BRANCH = "claude-code-staging"

_REQUIRED_SCENARIO_KEYS = ("scenario_id", "task", "test_command")


class ApprovalGate(Protocol):
    """Human-in-the-Loop approval hook for destructive execution (#384).

    Satisfied by :class:`rfc.hitl_gate.HitlApprovalGate`. ``require`` must
    raise (``HitlApprovalError``) unless an approved, unexpired
    ``hitl_interactions`` row binds exactly this action id and args digest.
    """

    def require(self, target_action_id: str, args: Mapping[str, Any]) -> None: ...


def sandbox_action_id(scenario_id: str, variant: str) -> str:
    """Canonical HITL action id for one sandboxed scenario run."""
    return f"agent-sandbox:{scenario_id}:{variant}"


def sandbox_action_args(
    scenario_id: str, variant: str, agent_id: str
) -> dict[str, str]:
    """Canonical HITL action args for one sandboxed scenario run.

    The approval-request side must digest exactly these args (via
    ``rfc.hitl_gate.compute_args_digest``) for the gate to open.
    """
    return {"scenario_id": scenario_id, "variant": variant, "agent_id": agent_id}


class ContainerBackend(Protocol):
    """The slice of ContainerManager the sandbox needs (injectable in tests)."""

    def create_container(self, config: Any, name: Optional[str] = None) -> str: ...

    def execute_command(
        self,
        container_id: str,
        command: str,
        timeout: int = 30,
        workdir: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def copy_to_container(
        self, container_id: str, host_path: str, container_path: str
    ) -> None: ...

    def stop_container(self, container_id: str, timeout: int = 10) -> None: ...


@dataclass(frozen=True)
class SandboxScenario:
    """One sandbox scenario loaded from a fixture directory."""

    scenario_id: str
    task: str
    test_command: str
    allowed_paths: tuple[str, ...]
    agents: Mapping[str, str]
    root: Path

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

    def agent_script(self, variant: str) -> Path:
        if variant not in self.agents:
            raise KeyError(
                f"Scenario {self.scenario_id!r} has no agent variant {variant!r}. "
                f"Available: {sorted(self.agents)}"
            )
        return self.root / self.agents[variant]


def load_sandbox_scenario(scenario_dir: Path | str) -> SandboxScenario:
    """Load and validate a sandbox scenario fixture directory."""
    root = Path(scenario_dir)
    yaml_path = root / "scenario.yaml"
    if not yaml_path.is_file():
        raise ValueError(f"Sandbox scenario missing {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text()) or {}

    missing = [k for k in _REQUIRED_SCENARIO_KEYS if not raw.get(k)]
    if missing:
        raise ValueError(f"Sandbox scenario {yaml_path} missing keys: {missing}")

    repo_dir = root / "repo"
    if not repo_dir.is_dir():
        raise ValueError(
            f"Sandbox scenario {root} has no repo/ directory to seed the container"
        )

    agents = {str(k): str(v) for k, v in (raw.get("agents") or {}).items()}
    if not agents:
        raise ValueError(f"Sandbox scenario {yaml_path} declares no agents")
    for variant, rel_path in agents.items():
        if not (root / rel_path).is_file():
            raise ValueError(
                f"Sandbox scenario {root.name}: agent variant {variant!r} "
                f"points at missing script {rel_path!r}"
            )

    return SandboxScenario(
        scenario_id=str(raw["scenario_id"]),
        task=str(raw["task"]),
        test_command=str(raw["test_command"]),
        allowed_paths=tuple(str(p) for p in raw.get("allowed_paths") or ()),
        agents=agents,
        root=root,
    )


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one sandboxed agent run, ready for Robot assertions."""

    scenario_id: str
    agent_id: str
    variant: str
    agent_exit_code: int
    agent_output_tail: str
    tests_exit_code: int
    tests_output_tail: str
    changed_paths: tuple[str, ...]
    unexpected_paths: tuple[str, ...]
    duration_seconds: float
    run: AgentRun

    @property
    def tests_passed(self) -> bool:
        return self.tests_exit_code == 0

    @property
    def has_unexpected_churn(self) -> bool:
        return bool(self.unexpected_paths)


def parse_manifest(text: str) -> dict[str, str]:
    """Parse ``sha256sum`` output into {workspace-relative path: digest}."""
    manifest: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, path = line.partition("  ")
        if not path:
            continue
        rel = path.removeprefix(f"{_WORKSPACE}/")
        manifest[rel] = digest
    return manifest


def diff_manifests(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    """Paths added, removed, or modified between two manifests (sorted)."""
    changed = {
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    }
    return tuple(sorted(changed))


def filter_unexpected(
    changed: tuple[str, ...], allowed: tuple[str, ...]
) -> tuple[str, ...]:
    """Changed paths not covered by an allowed exact path or directory prefix."""

    def is_allowed(path: str) -> bool:
        return any(
            path == entry or (entry.endswith("/") and path.startswith(entry))
            for entry in allowed
        )

    return tuple(p for p in changed if not is_allowed(p))


def _tail(text: str) -> str:
    return text[-_OUTPUT_TAIL_CHARS:]


class AgentSandbox:
    """Run agent commands against disposable scenario repos inside Docker."""

    def __init__(
        self,
        limits: SandboxLimits,
        manager: ContainerBackend | None = None,
        scenarios_root: Path | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self.limits = limits
        self._manager = manager
        self._scenarios_root = scenarios_root or DEFAULT_SANDBOX_SCENARIOS_ROOT
        # HITL enforcement (#384): when a gate is configured, run_scenario
        # refuses to touch Docker unless the exact action is approved.
        # None keeps the historical ungated behaviour (opt-in per harness).
        self._approval_gate = approval_gate

    @property
    def manager(self) -> ContainerBackend:
        """Lazy ContainerManager: raises DockerNotAvailableError (skip) sans daemon."""
        if self._manager is None:
            from rfc.container_manager import ContainerManager

            self._manager = ContainerManager()
        return self._manager

    def _resolve_scenario(
        self, scenario: SandboxScenario | Path | str
    ) -> SandboxScenario:
        if isinstance(scenario, SandboxScenario):
            return scenario
        path = Path(scenario)
        if not path.is_absolute() and not path.is_dir():
            path = self._scenarios_root / str(scenario)
        return load_sandbox_scenario(path)

    def _container_config(self, scenario_id: str, variant: str) -> Any:
        from rfc.docker_config import (
            ContainerConfig,
            ContainerNetwork,
            ContainerResources,
        )

        resources = ContainerResources(
            cpu_quota=int(self.limits.cpu_cores * 100000),
            memory_mb=self.limits.memory_mb,
        )
        return ContainerConfig(
            image=self.limits.image,
            name=f"rfc-sandbox-{scenario_id}-{variant}",
            command="sleep infinity",
            resources=resources,
            network=ContainerNetwork(mode=self.limits.network_mode),
            labels={"rfc.suite": "agentic-coding", "rfc.tier": "4"},
            read_only=False,
            user="root",
            working_dir=_WORKSPACE,
        )

    def _manifest(self, container_id: str) -> dict[str, str]:
        result = self.manager.execute_command(
            container_id, _MANIFEST_COMMAND, timeout=60
        )
        if result["exit_code"] != 0:
            raise RuntimeError(
                f"Workspace manifest failed (exit {result['exit_code']}): "
                f"{_tail(result['stdout'])}"
            )
        return parse_manifest(result["stdout"])

    def run_scenario(
        self,
        scenario: SandboxScenario | Path | str,
        variant: str = "good",
        agent_id: str = "claude-code",
    ) -> SandboxResult:
        """Seed, run the agent variant, and verify the resulting worktree.

        With an ``approval_gate`` configured, execution is blocked fail-closed
        (before any container exists) unless an approved ``hitl_interactions``
        row matches this exact action id + args digest (#384).
        """
        resolved = self._resolve_scenario(scenario)
        if self._approval_gate is not None:
            self._approval_gate.require(
                sandbox_action_id(resolved.scenario_id, variant),
                sandbox_action_args(resolved.scenario_id, variant, agent_id),
            )
        script = resolved.agent_script(variant)
        config = self._container_config(resolved.scenario_id, variant)
        wall_clock = self.limits.wall_clock_seconds

        started = time.time()
        container_id = self.manager.create_container(config)
        logger.info(
            f"Sandbox up for {resolved.scenario_id}/{variant} "
            f"({self.limits.image}, cpu={self.limits.cpu_cores}, "
            f"mem={self.limits.memory_mb}MB, wall={wall_clock}s, "
            f"net={self.limits.network_mode})"
        )
        try:
            self.manager.copy_to_container(
                container_id, str(resolved.repo_dir), _WORKSPACE
            )
            baseline = self._manifest(container_id)

            self.manager.copy_to_container(container_id, str(script), _AGENT_SCRIPT_DIR)
            agent_command = (
                f"timeout -k {_KILL_AFTER_SECONDS}s {wall_clock}s "
                f"sh {_AGENT_SCRIPT_DIR}/{script.name}"
            )
            agent_result = self.manager.execute_command(
                container_id,
                agent_command,
                timeout=wall_clock + 30,
                workdir=_WORKSPACE,
            )

            after = self._manifest(container_id)
            changed = diff_manifests(baseline, after)
            unexpected = filter_unexpected(changed, resolved.allowed_paths)

            test_command = (
                f"timeout -k {_KILL_AFTER_SECONDS}s {wall_clock}s "
                f"{resolved.test_command}"
            )
            tests_result = self.manager.execute_command(
                container_id,
                test_command,
                timeout=wall_clock + 30,
                workdir=_WORKSPACE,
            )
        finally:
            self.manager.stop_container(container_id)

        duration = time.time() - started
        run = AgentRun(
            agent_id=agent_id,
            scenario_id=resolved.scenario_id,
            task=resolved.task,
            base_branch=_SANDBOX_BASE_BRANCH,
            branch_name=f"sandbox/{resolved.scenario_id}",
            commands=(
                AgentCommand(
                    argv=("sh", "-c", agent_command),
                    cwd=_WORKSPACE,
                    returncode=int(agent_result["exit_code"]),
                    stdout_tail=_tail(agent_result["stdout"]),
                    changed_paths_after=changed,
                ),
                AgentCommand(
                    argv=("sh", "-c", test_command),
                    cwd=_WORKSPACE,
                    returncode=int(tests_result["exit_code"]),
                    stdout_tail=_tail(tests_result["stdout"]),
                    changed_paths_after=changed,
                ),
            ),
        )
        result = SandboxResult(
            scenario_id=resolved.scenario_id,
            agent_id=agent_id,
            variant=variant,
            agent_exit_code=int(agent_result["exit_code"]),
            agent_output_tail=_tail(agent_result["stdout"]),
            tests_exit_code=int(tests_result["exit_code"]),
            tests_output_tail=_tail(tests_result["stdout"]),
            changed_paths=changed,
            unexpected_paths=unexpected,
            duration_seconds=round(duration, 3),
            run=run,
        )
        logger.info(
            f"Sandbox run {resolved.scenario_id}/{variant}: "
            f"agent_exit={result.agent_exit_code} "
            f"tests_exit={result.tests_exit_code} "
            f"changed={list(changed)} unexpected={list(unexpected)} "
            f"({result.duration_seconds}s)"
        )
        return result
