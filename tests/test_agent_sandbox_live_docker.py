"""Real-Docker integration coverage for the #174 live-harness sync seam.

The hermetic unit tests in ``test_agent_sandbox.py`` inject a ``FakeContainerManager``
and hand the harness pre-baked manifests, so the novel part of the live path --
the clear-then-copy *sync* into a real container and the churn diff over what the
sync actually produced -- is never exercised against Docker. These tests close
that gap: they drive ``AgentSandbox._run_live_scenario`` against a **real**
``ContainerManager`` with a fake invoker that mutates the throwaway host
workspace the way a live agent could, then assert what the container-side
manifest + churn diff observed.

Skips cleanly (never fails) when the Docker daemon is unavailable, mirroring the
tier:4 robot suite -- so CI without Docker stays green while a box with Docker
gets the real coverage.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from rfc.agent_config import SandboxLimits
from rfc.agent_sandbox import DEFAULT_SANDBOX_SCENARIOS_ROOT, AgentSandbox
from rfc.exceptions import DockerNotAvailableError
from rfc.harness_adapters import ClaudeProcessResult

BUG_FIX_DIR = DEFAULT_SANDBOX_SCENARIOS_ROOT / "tier4_bug_fix"
_BUG = "def subtract(a, b):\n    return a + b  # BUG: should be a - b\n"
_FIX = "def subtract(a, b):\n    return a - b\n"


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
        pytest.skip("Docker daemon unavailable; live sandbox sync seam not exercised")


def _apply_fix(workspace: Path) -> None:
    calc = workspace / "calculator.py"
    calc.write_text(calc.read_text().replace(_BUG, _FIX))


def _run(manager, mutate):
    """Drive one live scenario; ``mutate(workspace)`` stands in for the agent."""

    def invoker(argv, cwd, env, timeout):
        mutate(Path(cwd))
        return ClaudeProcessResult(returncode=0, stdout="", stderr="")

    sandbox = AgentSandbox(limits=_limits(), manager=manager, invoker=invoker)
    return sandbox.run_scenario(
        BUG_FIX_DIR, variant="opencode", agent_id="opencode", harness="opencode"
    )


class TestLiveSyncSeamRealDocker:
    def test_clean_fix_has_no_unexpected_churn(self, docker_manager) -> None:
        # Baseline: a real container manifests the synced workspace; a clean fix
        # touches only calculator.py (an allowed path) and the tests go green.
        result = _run(docker_manager, _apply_fix)
        assert result.changed_paths == ("calculator.py",)
        assert result.unexpected_paths == ()
        assert result.tests_passed
        assert not result.has_unexpected_churn

    def test_delete_aware_sync_flags_removed_seeded_file(self, docker_manager) -> None:
        # The clear-then-copy sync must reflect host-side *deletions* in the
        # container so they register as churn. Without the `-mindepth 1 -delete`
        # reset the baseline copy of test_calculator.py would survive and the
        # deletion would go unseen. test_calculator.py is not in allowed_paths.
        def mutate(ws: Path) -> None:
            _apply_fix(ws)
            (ws / "test_calculator.py").unlink()

        result = _run(docker_manager, mutate)
        assert "test_calculator.py" in result.changed_paths
        assert result.unexpected_paths == ("test_calculator.py",)
        assert result.has_unexpected_churn

    def test_out_of_allowlist_churn_flagged(self, docker_manager) -> None:
        # A real tar round-trip + `sha256sum` manifest must surface scratch
        # files outside allowed_paths -- including nested, dotfile, and
        # unicode/space names -- while leaving the allowed calculator.py clean.
        def mutate(ws: Path) -> None:
            _apply_fix(ws)
            (ws / "debug.log").write_text("junk\n")
            (ws / "sub").mkdir()
            (ws / "sub" / "extra.py").write_text("x = 1\n")
            (ws / ".sneaky").write_text("hidden\n")
            (ws / "na me €.txt").write_text("weird\n")

        result = _run(docker_manager, mutate)
        assert result.unexpected_paths == (
            ".sneaky",
            "debug.log",
            "na me €.txt",
            "sub/extra.py",
        )
        assert "calculator.py" not in result.unexpected_paths
        assert result.has_unexpected_churn

    def test_symlink_to_host_file_does_not_leak_host_content(
        self, docker_manager
    ) -> None:
        # Safety: an agent that replaces a file with a symlink pointing OUTSIDE
        # the workspace must not exfiltrate host content into the graded result.
        # The tar sync copies the link (never dereferences it host-side), so it
        # resolves inside the network-isolated container -- to the CONTAINER's
        # /etc/hostname, never the host's -- proving no host-file escape.
        host_hostname = os.uname().nodename

        def mutate(ws: Path) -> None:
            (ws / "calculator.py").unlink()
            os.symlink("/etc/hostname", ws / "calculator.py")

        result = _run(docker_manager, mutate)
        assert host_hostname not in result.tests_output_tail
