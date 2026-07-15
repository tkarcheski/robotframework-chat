"""Docker-sandboxed execution harness for the agentic-coding suite (tier:4).

Spins up a disposable container, seeds it with a scenario repo, runs an agent
command inside it under resource caps, then verifies the resulting worktree
state: the scenario's tests still pass and no unexpected file churn occurred.

The agent side is deliberately pluggable. Each scenario ships scripted agent
variants (``agents/*.sh``) that run inside the container and stay the default
for deterministic CI. Passing ``harness=<name>`` (a :data:`rfc.harness_cli.TOOLS`
taxonomy name) instead drives a *live* coding-agent CLI through its
:class:`~rfc.harness_adapters.HarnessAdapter` (Issue #174). Per the owner's
ratified egress model (decision 2) as sharpened by the #235 coherence ruling,
the live harness *head* -- model I/O, reasoning, clarifying questions -- runs ON
THE HOST, but its code-exec *hands* -- bash/write/edit -- route through the
host-side :class:`~rfc.container_exec_broker.ContainerExecBroker` INTO a
pre-warmed, network-isolated container whose ``/workspace`` is the single working
tree. The churn diff + ``test_command`` then run in place against exactly what
the agent produced (no host-side copy-back). An absent harness CLI skips the run
cleanly (:class:`~rfc.exceptions.HarnessNotAvailableError`). Only harnesses whose
code-exec actually routes into the container (``claude-code`` #235, ``opencode``
#381, see :data:`_CONTAINER_ROUTED_HARNESSES`) may take this path; a still-host-
native harness (``codex`` -- CLI absent, exec un-routed) FAILS CLOSED with
:class:`~rfc.exceptions.LiveHarnessNotRoutedError` rather than be verified
against a ``/workspace`` its edits never reached (#377). Every run is
normalized into the same :class:`~rfc.agent_run.AgentRun` the rest of the suite's
verifiers consume.

Scenario fixture layout::

    robot/40__tier4/agentic_coding/fixtures/sandbox/
      <scenario_id>/
        scenario.yaml      # task, test_command, allowed_paths, agent variants
        repo/              # disposable repo seeded into the container
        agents/<name>.sh   # scripted agent variants (live adapter follow-up)

Docker unavailability raises :class:`~rfc.exceptions.DockerNotAvailableError`
(``ROBOT_SKIP_EXECUTION``), so Robot tests skip cleanly without a daemon.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol

import yaml
from robot.api import logger

from rfc.agent_config import SandboxLimits
from rfc.agent_run import AgentCommand, AgentRun
from rfc.churn_manifest import (
    diff_manifests,
    filter_unexpected,
    manifest_command,
    parse_manifest,
)
from rfc.container_exec_broker import check_overhead_budget, read_overhead_samples
from rfc.exceptions import HarnessNotAvailableError, LiveHarnessNotRoutedError
from rfc.exec_mcp import SandboxExecRouting
from rfc.harness_adapters import (
    HarnessAdapter,
    OpenCodeAdapter,
    ProcessInvoker,
    _default_invoker,
    get_adapter,
    make_branch_name,
    redact,
)

DEFAULT_SANDBOX_SCENARIOS_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "robot"
    / "40__tier4"
    / "agentic_coding"
    / "fixtures"
    / "sandbox"
)

# Repo ``opencode.json`` (local Ollama, no external egress) exported as
# OPENCODE_CONFIG when a live opencode harness drives a scenario (#174). Lives
# at the core/ root, two parents up from this package (src/rfc/ -> src/ -> core/).
_DEFAULT_OPENCODE_CONFIG = (
    Path(__file__).resolve().parent.parent.parent / "opencode.json"
)

_WORKSPACE = "/workspace"
_AGENT_SCRIPT_DIR = "/tmp"
_OUTPUT_TAIL_CHARS = 4000
# Grace period between SIGTERM and SIGKILL for `timeout -k`. Without the
# escalation, an agent (or child) that ignores SIGTERM outlives the
# advertised wall-clock cap and can hang the suite (PR #490 review, P1).
_KILL_AFTER_SECONDS = 10
# Exit code GNU ``timeout(1)`` emits when it kills a command that overran its
# wall-clock cap (also what the live path stamps on ``TimeoutExpired``). #251:
# this module is the single point of truth that turns 124 into the explicit
# ``timed_out`` flag on :class:`SandboxResult`, so no consumer re-derives a
# harness kill from a magic number -- a live CLI can itself exit 124 for
# reasons unrelated to a timeout.
TIMEOUT_EXIT_CODE = 124
# Live harnesses whose per-tool-call code execution ROUTES INTO the verification
# container today (via the ``rfc-exec`` MCP broker, #235). Single source of truth
# for both ``_wire_exec_routing`` and the ``_run_live_scenario`` fail-closed gate.
# claude-code (#235) and opencode (#381 F5, live-conformed against opencode 1.2.9)
# both have a live-verified broker path: their native code tools are denied and
# bash/write/edit route into the container ``/workspace``. codex code-exec is
# still host-native AND its CLI is absent (probe-gated), so it FAILS CLOSED --
# container-verifying it would compare a fix against a pristine tree it never
# touched (#377). A harness joins this set ONLY after its own live conformance
# passes -- one live-verified harness at a time; the fail-closed guard is the
# permanent invariant, never removed (#378 ruling).
_CONTAINER_ROUTED_HARNESSES: frozenset[str] = frozenset({"claude-code", "opencode"})
_SANDBOX_BASE_BRANCH = "claude-code-staging"

_REQUIRED_SCENARIO_KEYS = ("scenario_id", "task", "test_command")


class ApprovalGate(Protocol):
    """Human-in-the-Loop approval hook for destructive execution (#384).

    Satisfied by :class:`rfc.hitl_gate.HitlApprovalGate`. ``require`` must
    raise (``HitlApprovalError``) unless an approved, unexpired
    ``hitl_interactions`` row binds exactly this action id and args digest.
    """

    def require(self, target_action_id: str, args: Mapping[str, Any]) -> None: ...


def sandbox_action_id(
    scenario_id: str, variant: str, harness: str | None = None
) -> str:
    """Canonical HITL action id for one sandboxed scenario run.

    ``harness=None`` is the scripted, in-container CI path; its id is left
    byte-identical to the historical form so pre-existing scripted approvals
    keep opening. A live harness (``harness=<name>``) drives a coding-agent CLI
    ON THE HOST (owner egress decision 2) -- a materially higher-consequence
    action -- so it gets a ``:live:<harness>`` discriminator.

    The ``:live:<harness>`` discriminator is a human-readable **index/label,
    not a security boundary** -- it is forgeable via any interpolated field
    (e.g. a crafted ``variant``), which is harmless precisely because it is
    never trusted alone. What actually stops a scripted approval from being
    replayed onto a live harness (#360 / mirror #657) is the **args digest**:
    ``rfc.hitl_gate`` opens the gate only on an ``id AND digest`` match, and
    scripted args (3 keys) and live args (5 keys: +``harness``
    +``harness_model``) have **disjoint key sets**, so a scripted approval's
    digest can never satisfy a live action's gate.
    """
    base = f"agent-sandbox:{scenario_id}:{variant}"
    if harness is None:
        return base
    return f"{base}:live:{harness}"


def sandbox_action_args(
    scenario_id: str,
    variant: str,
    agent_id: str,
    harness: str | None = None,
    harness_model: str = "",
) -> dict[str, str]:
    """Canonical HITL action args for one sandboxed scenario run.

    The approval-request side must digest exactly these args (via
    ``rfc.hitl_gate.compute_args_digest``) for the gate to open. For a live
    harness the args carry ``harness`` + ``harness_model`` so the approval binds
    the exact CLI (and, for adapters that take one, the exact model) the human
    signed off on -- an approval for ``harness="opencode"`` will not open a run
    for ``harness="codex"`` or a different model. Scripted (``harness=None``)
    args are left unchanged so historical scripted approvals still verify.
    """
    args = {"scenario_id": scenario_id, "variant": variant, "agent_id": agent_id}
    if harness is not None:
        args["harness"] = harness
        args["harness_model"] = harness_model
    return args


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
    # #251: explicit timeout flags, set at the single point of truth (this
    # module) so a scoreboard reads a flag rather than inferring a harness
    # kill from ``agent_exit_code == 124``. ``timed_out`` == the agent/harness
    # overran its wall-clock cap; ``tests_timed_out`` == the verification
    # ``test_command`` overran its cap. Additive + backward compatible: both
    # default False and existing 124 readers keep working.
    timed_out: bool = False
    tests_timed_out: bool = False
    # #235: per-code-exec-call broker overhead samples (ms), one per tool call
    # the live agent routed into the container. Empty on the scripted path and on
    # any live path that did not route code-exec through the broker. Surfaced so
    # the perf budget (p50 <= 120ms / p95 <= 300ms) is auditable from the result.
    sandbox_exec_overhead_ms: tuple[float, ...] = ()

    @property
    def tests_passed(self) -> bool:
        return self.tests_exit_code == 0

    @property
    def has_unexpected_churn(self) -> bool:
        return bool(self.unexpected_paths)


def _tail(text: str) -> str:
    return text[-_OUTPUT_TAIL_CHARS:]


def _coerce_text(value: Any) -> str:
    """Normalize subprocess output (bytes / str / None) to str."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class AgentSandbox:
    """Run agent commands against disposable scenario repos inside Docker."""

    def __init__(
        self,
        limits: SandboxLimits,
        manager: ContainerBackend | None = None,
        scenarios_root: Path | None = None,
        approval_gate: ApprovalGate | None = None,
        invoker: ProcessInvoker | None = None,
        opencode_config: Path | None = None,
    ) -> None:
        self.limits = limits
        self._manager = manager
        self._scenarios_root = scenarios_root or DEFAULT_SANDBOX_SCENARIOS_ROOT
        # HITL enforcement (#384): when a gate is configured, run_scenario
        # refuses to touch Docker unless the exact action is approved.
        # None keeps the historical ungated behaviour (opt-in per harness).
        self._approval_gate = approval_gate
        # Host-side agent invocation seam for the live-harness path (#174).
        # None -> the real subprocess invoker (production). An injected invoker
        # replays a recorded transcript AND disables the probe gate, so unit
        # tests never need the real CLI installed (mirrors LiveClaudeCodeRunner).
        self._agent_invoker = invoker or _default_invoker
        self._probe_live = invoker is None
        self._opencode_config = opencode_config or _DEFAULT_OPENCODE_CONFIG

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
            container_id, manifest_command(), timeout=60
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
        harness: str | None = None,
        harness_model: str = "",
    ) -> SandboxResult:
        """Seed, run the agent, and verify the resulting worktree.

        ``harness=None`` (the default) runs the scenario's scripted
        ``agents/<variant>.sh`` stand-in inside the container -- the
        deterministic CI path. ``harness=<name>`` (a :data:`rfc.harness_cli.TOOLS`
        taxonomy name) instead drives that live coding-agent CLI host-side
        against the seeded repo (owner egress decision 2), with the container
        still verifying churn + tests; an absent harness CLI raises
        :class:`~rfc.exceptions.HarnessNotAvailableError` (a clean skip).
        ``harness_model`` overrides the model for adapters that take one
        (opencode).

        With an ``approval_gate`` configured, execution is blocked fail-closed
        (before any container OR host agent is launched) unless an approved
        ``hitl_interactions`` row matches this exact action id + args digest
        (#384). The binding includes ``harness`` + ``harness_model`` (#360), so
        the scripted and live paths are gated as *distinct digests*: a scripted
        approval can never be replayed onto a host-side live harness the human
        never approved.
        """
        resolved = self._resolve_scenario(scenario)
        if self._approval_gate is not None:
            self._approval_gate.require(
                sandbox_action_id(resolved.scenario_id, variant, harness),
                sandbox_action_args(
                    resolved.scenario_id, variant, agent_id, harness, harness_model
                ),
            )
        if harness is not None:
            return self._run_live_scenario(
                resolved, variant, agent_id, harness, harness_model
            )
        return self._run_scripted_scenario(resolved, variant, agent_id)

    def _run_scripted_scenario(
        self, resolved: SandboxScenario, variant: str, agent_id: str
    ) -> SandboxResult:
        """Scripted stand-in path: the agent variant runs inside the container."""
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
        # Scripted path single point of truth: the agent + test commands are
        # each wrapped in ``timeout -k``, so an exit of TIMEOUT_EXIT_CODE is
        # unambiguously our wrapper killing an overrun (not a consumer's guess).
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
            timed_out=int(agent_result["exit_code"]) == TIMEOUT_EXIT_CODE,
            tests_timed_out=int(tests_result["exit_code"]) == TIMEOUT_EXIT_CODE,
        )
        logger.info(
            f"Sandbox run {resolved.scenario_id}/{variant}: "
            f"agent_exit={result.agent_exit_code} "
            f"tests_exit={result.tests_exit_code} "
            f"changed={list(changed)} unexpected={list(unexpected)} "
            f"({result.duration_seconds}s)"
        )
        return result

    def _build_harness_adapter(
        self, harness: str, harness_model: str
    ) -> HarnessAdapter:
        """Construct the adapter for ``harness``, wiring opencode's local config.

        opencode reuses the repo ``opencode.json`` (local Ollama, no external
        egress) via ``OPENCODE_CONFIG`` and accepts a ``--model`` override;
        claude-code and codex take no model override here. Unknown names raise
        ``KeyError`` (a typo, not a skip).
        """
        if harness == "opencode":
            config_path = (
                self._opencode_config if self._opencode_config.exists() else None
            )
            return OpenCodeAdapter(model=harness_model or None, config_path=config_path)
        return get_adapter(harness)

    def _wire_exec_routing(
        self, adapter: HarnessAdapter, container_id: str, metrics_path: Path
    ) -> None:
        """Point the adapter's code-exec tools at the pre-warmed container (#235/#381).

        claude-code and opencode both have a live-verified broker path: their
        native code tools are denied and code execution routes through the
        rfc-exec MCP server into ``container_id``. codex isn't installed and
        isn't routed, so it stays host-native (and never reaches here --
        ``_run_live_scenario`` fails it closed first). ``metrics_path`` is where
        the broker child appends per-call overhead samples for this process to
        collect after the run.

        Wiring is two-step and adapter-shaped: setting ``exec_routing`` hands the
        runtime container id (unknown at build time) to the adapter. claude-code
        then emits its deny-settings + mcp-config inline on argv. opencode instead
        consumes a config FILE, so it additionally materializes a merged routed
        config (base opencode.json + the exec overlay) into the run's temp dir via
        ``apply_routed_config``; ``env_overrides`` then exports it as
        OPENCODE_CONFIG. Both land in ``_CONTAINER_ROUTED_HARNESSES``; the guard
        stays as defence in depth and is unit-tested directly.
        """
        if adapter.name not in _CONTAINER_ROUTED_HARNESSES:
            return
        routing = SandboxExecRouting(
            container_id=container_id, metrics_path=str(metrics_path)
        )
        # Adapters carry a mutable exec_routing attribute; setting it here (post
        # container-create) is how the runtime container id reaches build_argv /
        # the routed config, which the adapter constructor can't know at build time.
        setattr(adapter, "exec_routing", routing)
        # opencode routes via a materialized merged config file (not inline argv
        # like claude-code); write it beside the metrics sink so it is torn down
        # with the run. Adapters without this hook (claude-code) route inline.
        apply_routed_config = getattr(adapter, "apply_routed_config", None)
        if callable(apply_routed_config):
            apply_routed_config(metrics_path.parent)

    def _invoke_agent_bounded(
        self,
        adapter: HarnessAdapter,
        agent_argv: tuple[str, ...],
        workspace: Path,
        wall_clock: int,
    ) -> tuple[int, str, bool]:
        """Run the host-side agent, bounding it to the wall-clock cap.

        Returns ``(returncode, stdout, timed_out)``. ``timed_out`` is the
        single point of truth for the live path (#251): it is True only when
        the invoker's ``TimeoutExpired`` fired -- i.e. the harness genuinely
        overran its wall-clock cap. A live CLI that *itself* exits
        ``TIMEOUT_EXIT_CODE`` for an unrelated reason is NOT flagged, so a
        consumer never conflates a harness kill with an agent-chosen 124.
        A live harness that overruns the cap is killed by the invoker's
        timeout with whatever partial transcript was captured, so the run
        always yields a bounded :class:`SandboxResult` rather than raising
        and leaving the scenario half-verified.
        """
        try:
            result = self._agent_invoker(
                agent_argv, workspace, adapter.env_overrides(), wall_clock
            )
            return int(result.returncode), result.stdout, False
        except subprocess.TimeoutExpired as exc:
            logger.warn(
                f"Live harness {adapter.name!r} exceeded the {wall_clock}s "
                f"wall-clock cap; terminating (exit {TIMEOUT_EXIT_CODE})."
            )
            return TIMEOUT_EXIT_CODE, _coerce_text(exc.stdout), True

    def _run_live_scenario(
        self,
        resolved: SandboxScenario,
        variant: str,
        agent_id: str,
        harness: str,
        harness_model: str,
    ) -> SandboxResult:
        """Live-harness path: the agent's code-exec routes INTO the container.

        Egress model (#235 coherence ruling, on top of owner decision 2): the
        harness process (the *head* -- model I/O, reasoning, clarifying
        questions) runs ON THE HOST, but its code-exec tool calls (the *hands* --
        bash/write/edit) route through the host-side ContainerExecBroker into a
        pre-warmed, network-isolated container. The container's ``/workspace`` is
        the single working tree, seeded from the pristine repo at t0; the churn
        manifest + ``test_command`` run in place against exactly what the agent
        produced -- no host-side copy-back (``_sync_workspace`` is gone). Each
        broker dispatch records ``sandbox_exec_overhead_ms``; the perf budget is
        checked and logged.

        FAIL CLOSED for non-routed harnesses (#377): container-verification is
        only honest when the harness's code-exec actually routes into
        ``/workspace``. codex is still host-native (CLI absent, exec un-routed),
        so its edits would land in a throwaway host tree the container never sees
        -- verifying against the pristine ``/workspace`` would silently record a
        wrong result (a red-seed fix always reads as "not fixed"). Rather than
        corrupt the sacred Tier-A spine, the run refuses with
        :class:`~rfc.exceptions.LiveHarnessNotRoutedError` (a clean skip) before
        any container is created. opencode crossed this guard on live conformance
        (#381); codex crosses it only once its exec is wired + verified (#378).
        """
        adapter = self._build_harness_adapter(harness, harness_model)
        # Probe-gate only the production path: an injected invoker means a test
        # replaying a recorded transcript, which must not require the real CLI.
        if self._probe_live and not adapter.probe():
            raise HarnessNotAvailableError(harness)
        # Fail closed BEFORE any container work: a host-native harness cannot be
        # container-verified without silently ignoring the agent's actual edits.
        if adapter.name not in _CONTAINER_ROUTED_HARNESSES:
            raise LiveHarnessNotRoutedError(harness)

        wall_clock = self.limits.wall_clock_seconds
        config = self._container_config(resolved.scenario_id, variant)
        started = time.time()

        # Pre-warm ONE network-isolated container and seed /workspace from the
        # pristine repo at t0, BEFORE the agent starts -- so its container id can
        # be handed to the broker and the agent's code-exec lands here in place.
        container_id = self.manager.create_container(config)
        logger.info(
            f"Sandbox up for {resolved.scenario_id}/{variant} "
            f"(harness={harness}, {self.limits.image}, "
            f"mem={self.limits.memory_mb}MB, wall={wall_clock}s, "
            f"net={self.limits.network_mode})"
        )
        overhead_samples: list[float] = []
        try:
            self.manager.copy_to_container(
                container_id, str(resolved.repo_dir), _WORKSPACE
            )
            baseline = self._manifest(container_id)

            with tempfile.TemporaryDirectory(
                prefix=f"rfc-sandbox-live-{resolved.scenario_id}-"
            ) as tmp:
                # Host CWD stub for the agent process, seeded identically at t0.
                # The agent's native code tools are denied; it reads via broker'd
                # ``bash cat`` so it never touches this stale stub (MVP ruling).
                agent_workspace = Path(tmp) / "workspace"
                shutil.copytree(resolved.repo_dir, agent_workspace)
                metrics_path = Path(tmp) / "exec_overhead.jsonl"
                self._wire_exec_routing(adapter, container_id, metrics_path)

                agent_argv = tuple(adapter.build_argv(resolved.task, agent_workspace))
                agent_returncode, agent_stdout, agent_timed_out = (
                    self._invoke_agent_bounded(
                        adapter, agent_argv, agent_workspace, wall_clock
                    )
                )
                overhead_samples = read_overhead_samples(metrics_path)

            # The agent mutated /workspace in place through the broker; observe
            # it directly -- no copy-back.
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
        budget = check_overhead_budget(overhead_samples)
        if overhead_samples and not budget.within_budget:
            logger.warn(
                f"Sandbox exec overhead OVER budget for {resolved.scenario_id}/"
                f"{variant} (harness={harness}): {budget.summary}"
            )
        commands, questions = adapter.parse_output(agent_stdout)
        test_row = AgentCommand(
            argv=("sh", "-c", test_command),
            cwd=_WORKSPACE,
            returncode=int(tests_result["exit_code"]),
            stdout_tail=_tail(tests_result["stdout"]),
            changed_paths_after=changed,
        )
        run = AgentRun(
            agent_id=agent_id,
            scenario_id=resolved.scenario_id,
            task=resolved.task,
            base_branch=_SANDBOX_BASE_BRANCH,
            branch_name=make_branch_name(resolved.task, prefix=adapter.branch_prefix),
            commands=(*commands, test_row),
            questions=questions,
        )
        result = SandboxResult(
            scenario_id=resolved.scenario_id,
            agent_id=agent_id,
            variant=variant,
            agent_exit_code=agent_returncode,
            agent_output_tail=_tail(redact(agent_stdout)),
            tests_exit_code=int(tests_result["exit_code"]),
            tests_output_tail=_tail(tests_result["stdout"]),
            changed_paths=changed,
            unexpected_paths=unexpected,
            duration_seconds=round(duration, 3),
            run=run,
            timed_out=agent_timed_out,
            tests_timed_out=int(tests_result["exit_code"]) == TIMEOUT_EXIT_CODE,
            sandbox_exec_overhead_ms=tuple(overhead_samples),
        )
        logger.info(
            f"Sandbox live run {resolved.scenario_id}/{variant} "
            f"(harness={harness}): agent_exit={result.agent_exit_code} "
            f"tests_exit={result.tests_exit_code} "
            f"changed={list(changed)} unexpected={list(unexpected)} "
            f"exec_overhead[{budget.summary}] "
            f"({result.duration_seconds}s)"
        )
        return result
