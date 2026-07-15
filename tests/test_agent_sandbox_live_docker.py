"""Real-Docker integration coverage for the #235 container-routed code-exec path.

The hermetic unit tests in ``test_agent_sandbox.py`` inject a FakeContainerManager
and hand the harness pre-baked manifests, so the real container-side work -- the
churn manifest + allowlist diff over what the agent actually produced in the
network-isolated container's ``/workspace`` -- is never exercised against Docker.
These tests close that gap: they drive ``AgentSandbox._run_live_scenario`` against
a **real** ``ContainerManager`` with a fake invoker that stands in for the live
agent by routing its code-exec mutations INTO the container's ``/workspace``
through a :class:`~rfc.container_exec_broker.ContainerExecBroker` -- exactly the
#235 seam -- then assert what the container-side manifest + churn diff observed.

Post-#235 there is no host-side copy-back: the container's ``/workspace`` is the
single working tree, seeded at t0, mutated in place by the agent's broker'd
tools, and manifested before/after. Skips cleanly (never fails) when the Docker
daemon is unavailable, so CI without Docker stays green while a box with Docker
gets the real coverage.
"""

from __future__ import annotations

import json
import os
import shlex
import uuid
from pathlib import Path

import pytest

from rfc.agent_config import SandboxLimits
from rfc.agent_sandbox import DEFAULT_SANDBOX_SCENARIOS_ROOT, AgentSandbox
from rfc.container_exec_broker import (
    ContainerExecBroker,
    SandboxToolCall,
    check_overhead_budget,
)
from rfc.exceptions import DockerNotAvailableError
from rfc.exec_mcp import CONTAINER_ID_ENV
from rfc.harness_adapters import ClaudeProcessResult

BUG_FIX_DIR = DEFAULT_SANDBOX_SCENARIOS_ROOT / "tier4_bug_fix"
_BUG_LINE = "return a + b  # BUG: should be a - b"
_FIX_LINE = "return a - b"


def _limits() -> SandboxLimits:
    return SandboxLimits(
        image="python:3.11-slim",
        cpu_cores=1.0,
        memory_mb=512,
        wall_clock_seconds=60,
        network_mode="none",
    )


@pytest.fixture()
def docker_manager():
    """A real ContainerManager, or skip if the Docker daemon is unreachable."""
    from rfc.container_manager import ContainerManager

    try:
        return ContainerManager()
    except DockerNotAvailableError:
        pytest.skip("Docker daemon unavailable; live exec-broker path not exercised")


class _ContainerFS:
    """Drive an agent's code-exec mutations into a real container via the broker.

    Every mutation is a :class:`SandboxToolCall` dispatched through a real
    :class:`ContainerExecBroker` against the run's container -- the same path a
    live claude-code agent's denied-and-rerouted tools take -- so these tests
    exercise the broker end-to-end against Docker, not just the churn math.
    """

    def __init__(self, manager, container_id: str) -> None:
        self._broker = ContainerExecBroker(manager, container_id)

    def bash(self, command: str) -> None:
        result = self._broker.dispatch(SandboxToolCall(kind="bash", payload=command))
        assert result.exit_code == 0, (command, result)

    def write(self, path: str, content: str) -> None:
        result = self._broker.dispatch(
            SandboxToolCall(kind="write", payload=content, path=path)
        )
        assert result.exit_code == 0, (path, result)

    def rm(self, path: str) -> None:
        self.bash(f"rm -f /workspace/{path}")

    def apply_fix(self) -> None:
        py = (
            "p='/workspace/calculator.py';s=open(p).read();"
            f"s=s.replace({_BUG_LINE!r},{_FIX_LINE!r});open(p,'w').write(s)"
        )
        self.bash("python3 -c " + shlex.quote(py))

    def symlink(self, target: str, name: str) -> None:
        py = f"import os;os.symlink({target!r}, '/workspace/{name}')"
        self.bash("python3 -c " + shlex.quote(py))


def _run(manager, mutate):
    """Drive one live scenario; ``mutate(fs)`` stands in for the agent's tools.

    The invoker plays the rfc-exec MCP child: it reads the run's container id out
    of the ``--mcp-config`` the sandbox threaded into claude-code's argv, then
    lets ``mutate`` route code-exec into that exact container.
    """

    def invoker(argv, cwd, env, timeout):
        argv_list = list(argv)
        mcp_json = argv_list[argv_list.index("--mcp-config") + 1]
        cid = json.loads(mcp_json)["mcpServers"]["rfc-exec"]["env"][CONTAINER_ID_ENV]
        mutate(_ContainerFS(manager, cid))
        return ClaudeProcessResult(returncode=0, stdout="", stderr="")

    sandbox = AgentSandbox(limits=_limits(), manager=manager, invoker=invoker)
    return sandbox.run_scenario(
        BUG_FIX_DIR,
        variant="claude-code",
        agent_id="claude-code",
        harness="claude-code",
    )


def _run_opencode(manager, mutate):
    """Drive one live opencode scenario against a REAL container (#381).

    opencode routes via a materialized merged config FILE (OPENCODE_CONFIG), not
    inline argv like claude-code, so this invoker reads the run's container id out
    of the ``mcp`` block of that merged config -- proving the sandbox wired
    opencode's routed config end-to-end -- then lets ``mutate`` route code-exec
    into that exact container through the broker (the same seam opencode's denied,
    rerouted native tools take live).
    """

    def invoker(argv, cwd, env, timeout):
        cfg = json.loads(Path(env["OPENCODE_CONFIG"]).read_text())
        cid = cfg["mcp"]["rfc-exec"]["environment"][CONTAINER_ID_ENV]
        # The merged routed config must actually deny opencode's native tools.
        assert cfg["permission"]["bash"] == "deny"
        mutate(_ContainerFS(manager, cid))
        return ClaudeProcessResult(returncode=0, stdout="", stderr="")

    sandbox = AgentSandbox(limits=_limits(), manager=manager, invoker=invoker)
    return sandbox.run_scenario(
        BUG_FIX_DIR,
        variant="opencode",
        agent_id="opencode",
        harness="opencode",
    )


class TestLiveOpenCodeExecBrokerRealDocker:
    """#381: opencode's routed config drives real edits into a real container."""

    def test_opencode_routed_fix_lands_in_container(self, docker_manager) -> None:
        # opencode's merged routed config binds the rfc-exec server to the run's
        # container; a fix routed through the broker lands in /workspace and is
        # observed by the in-place churn manifest -- no host-side copy-back.
        result = _run_opencode(docker_manager, lambda fs: fs.apply_fix())
        assert result.changed_paths == ("calculator.py",)
        assert result.unexpected_paths == ()
        assert result.tests_passed
        assert not result.has_unexpected_churn

    def test_opencode_routed_out_of_allowlist_churn_flagged(
        self, docker_manager
    ) -> None:
        # A scratch file opencode writes outside allowed_paths must register as
        # unexpected churn -- the same honest verification claude-code gets.
        def mutate(fs: _ContainerFS) -> None:
            fs.apply_fix()
            fs.write("debug.log", "junk\n")

        result = _run_opencode(docker_manager, mutate)
        assert result.unexpected_paths == ("debug.log",)
        assert result.has_unexpected_churn


class TestLiveExecBrokerRealDocker:
    def test_clean_fix_has_no_unexpected_churn(self, docker_manager) -> None:
        # A clean fix routed into /workspace touches only calculator.py (an
        # allowed path) and the tests go green -- observed by the in-place churn
        # manifest, no host-side copy-back.
        result = _run(docker_manager, lambda fs: fs.apply_fix())
        assert result.changed_paths == ("calculator.py",)
        assert result.unexpected_paths == ()
        assert result.tests_passed
        assert not result.has_unexpected_churn

    def test_deleted_seeded_file_registers_as_churn(self, docker_manager) -> None:
        # A file the agent deletes in-container must register as churn against the
        # t0 baseline. test_calculator.py is not in allowed_paths.
        def mutate(fs: _ContainerFS) -> None:
            fs.apply_fix()
            fs.rm("test_calculator.py")

        result = _run(docker_manager, mutate)
        assert "test_calculator.py" in result.changed_paths
        assert result.unexpected_paths == ("test_calculator.py",)
        assert result.has_unexpected_churn

    def test_out_of_allowlist_churn_flagged(self, docker_manager) -> None:
        # A real `sha256sum` manifest must surface scratch files outside
        # allowed_paths -- including nested, dotfile, and unicode/space names --
        # while leaving the allowed calculator.py clean.
        def mutate(fs: _ContainerFS) -> None:
            fs.apply_fix()
            fs.write("debug.log", "junk\n")
            fs.write("sub/extra.py", "x = 1\n")
            fs.write(".sneaky", "hidden\n")
            fs.write("na me €.txt", "weird\n")

        result = _run(docker_manager, mutate)
        assert result.unexpected_paths == (
            ".sneaky",
            "debug.log",
            "na me €.txt",
            "sub/extra.py",
        )
        assert "calculator.py" not in result.unexpected_paths
        assert result.has_unexpected_churn

    def test_out_of_allowlist_symlink_is_flagged(self, docker_manager) -> None:
        # #248: a symlink created OUTSIDE allowed_paths must register as
        # unexpected churn. The symlink-aware manifest folds the link target in
        # and flags it -- even when the task itself was solved cleanly.
        def mutate(fs: _ContainerFS) -> None:
            fs.apply_fix()
            fs.symlink("/etc/passwd", "escape")

        result = _run(docker_manager, mutate)
        assert "escape" in result.changed_paths
        assert result.unexpected_paths == ("escape",)
        assert result.has_unexpected_churn
        assert result.tests_passed

    def test_newline_target_symlink_is_flagged(self, docker_manager) -> None:
        # #248 REOPENED: an out-of-allowlist symlink whose target ENDS IN A
        # NEWLINE must still flag `escape` (the manifest must not split on the
        # target's raw newline and lose the entry).
        def mutate(fs: _ContainerFS) -> None:
            fs.apply_fix()
            fs.symlink("/etc/passwd\n", "escape")

        result = _run(docker_manager, mutate)
        assert "escape" in result.changed_paths
        assert result.unexpected_paths == ("escape",)
        assert result.has_unexpected_churn
        assert result.tests_passed

    def test_symlink_resolves_inside_container_not_host(self, docker_manager) -> None:
        # Safety: with code-exec confined to the container, a symlink the agent
        # creates resolves against the CONTAINER's filesystem, never the host's,
        # so host content cannot leak into the graded result.
        host_hostname = os.uname().nodename

        def mutate(fs: _ContainerFS) -> None:
            fs.rm("calculator.py")
            fs.symlink("/etc/hostname", "calculator.py")

        result = _run(docker_manager, mutate)
        assert host_hostname not in result.tests_output_tail


@pytest.fixture()
def live_container(docker_manager):
    """A real, running network=none container with an empty /workspace."""
    from rfc.docker_config import (
        ContainerConfig,
        ContainerNetwork,
        ContainerResources,
    )

    cfg = ContainerConfig(
        image="python:3.11-slim",
        name=f"rfc-235-broker-{uuid.uuid4().hex[:10]}",
        command="sleep infinity",
        resources=ContainerResources(cpu_quota=100000, memory_mb=512),
        network=ContainerNetwork(mode="none"),
        read_only=False,
        user="root",
        working_dir="/workspace",
    )
    cid = docker_manager.create_container(cfg)
    docker_manager.execute_command(
        cid, "mkdir -p /workspace", timeout=30, workdir="/workspace"
    )
    try:
        yield docker_manager, cid
    finally:
        docker_manager.stop_container(cid)


class TestBrokerWriteCeilingRealDocker:
    """#235 B3: writes above the inline argv ceiling succeed (chunked)."""

    def test_writes_survive_and_round_trip_above_the_96kb_ceiling(
        self, live_container
    ) -> None:
        manager, cid = live_container
        broker = ContainerExecBroker(manager, cid)
        for size_kb in (64, 96, 256, 1024):
            content = ("A" * 1023 + "\n") * size_kb  # size_kb KiB, incl. newlines
            path = f"big_{size_kb}.txt"
            result = broker.dispatch(
                SandboxToolCall(kind="write", payload=content, path=path)
            )
            assert result.exit_code == 0, (size_kb, result)
            back = manager.execute_command(
                cid, f"cat /workspace/{path}", timeout=60, workdir="/workspace"
            )
            assert back["stdout"] == content, size_kb


class TestBrokerConfinementRealDocker:
    """#235 S1: symlink-parent escapes are rejected in-container."""

    def test_symlink_parent_escape_is_rejected(self, live_container) -> None:
        manager, cid = live_container
        broker = ContainerExecBroker(manager, cid)
        # /workspace/link -> /tmp; a write through it would land outside the tree.
        manager.execute_command(
            cid, "ln -s /tmp /workspace/link", timeout=30, workdir="/workspace"
        )
        result = broker.dispatch(
            SandboxToolCall(kind="write", payload="pwned", path="link/escape")
        )
        assert result.exit_code != 0  # realpath guard fired
        check = manager.execute_command(
            cid, "cat /tmp/escape 2>/dev/null || true", timeout=30
        )
        assert "pwned" not in check["stdout"]  # nothing written outside /workspace

    def test_legit_nested_write_still_works(self, live_container) -> None:
        manager, cid = live_container
        broker = ContainerExecBroker(manager, cid)
        result = broker.dispatch(
            SandboxToolCall(kind="write", payload="ok\n", path="pkg/deep/mod.py")
        )
        assert result.exit_code == 0
        back = manager.execute_command(
            cid, "cat /workspace/pkg/deep/mod.py", timeout=30, workdir="/workspace"
        )
        assert back["stdout"] == "ok\n"


class TestBrokerOverheadRealDocker:
    """#235 B2: sandbox_exec_overhead_ms now includes the docker-exec transport."""

    def test_overhead_captures_transport_and_stays_within_budget(
        self, live_container
    ) -> None:
        manager, cid = live_container
        broker = ContainerExecBroker(manager, cid)
        for _ in range(25):
            broker.dispatch(SandboxToolCall(kind="bash", payload="true"))
        verdict = check_overhead_budget(broker.overhead_samples_ms)
        # The per-call docker-exec transport (tens of ms) is captured -- the
        # pre-fix metric recorded ~0 here by subtracting a transport-inclusive
        # duration. Still within the 120/300ms budget (honesty, not regression).
        assert verdict.p50_ms > 10.0
        assert verdict.within_budget
