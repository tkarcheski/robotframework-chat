"""Robot Framework keyword library driving the ``rfc harness`` CLI end-to-end.

Each keyword call that runs the CLI spawns a *separate* Python process
(``python -m rfc.harness_cli``) inside a throwaway git repo with its own
sqlite database, so the suite verifies the real cross-process contract:
the sidecar written by ``start`` must be readable by later ``status`` /
``end`` invocations and by ``makefile_session_id()`` (Issue #411).

Used by ``robot/10__tier1/harness/test_harness_cli.robot`` (tier:1, verify:python).
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

from robot.api.deco import keyword  # type: ignore[import-untyped]

from rfc.harness_db import HarnessDatabase

_SIDECAR_NAME = "rfc-harness-session.json"


class HarnessCliRunner:
    """RF keyword library for end-to-end ``rfc harness`` CLI testing."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    @keyword("Create Harness Workspace")
    def create_harness_workspace(self, root: str) -> dict:
        """Initialise a throwaway git repo + sqlite DB under ``root``.

        Args:
            root: Existing directory to turn into a workspace.

        Returns:
            Dict with ``path``, ``database_url`` and ``sidecar`` keys,
            passed to every other keyword in this library.
        """
        root_path = Path(root)
        subprocess.run(["git", "init", "-q"], cwd=root_path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "root",
            ],
            cwd=root_path,
            check=True,
        )
        return {
            "path": str(root_path),
            "database_url": f"sqlite:///{root_path / 'harness.db'}",
            "sidecar": str(root_path / ".git" / _SIDECAR_NAME),
        }

    @keyword("Run Harness Command")
    def run_harness_command(self, workspace: dict, *args: str) -> dict:
        """Run ``rfc harness <args>`` as a fresh subprocess in the workspace.

        ``--no-version-probe`` is appended to ``start`` so the test never
        shells out to a real agent binary.

        Args:
            workspace: Dict from `Create Harness Workspace`.
            args: CLI arguments after ``harness`` (e.g. ``start --tool codex``).

        Returns:
            Dict with ``rc``, ``stdout`` and ``stderr`` keys.
        """
        argv = [sys.executable, "-m", "rfc.harness_cli", "harness", *args]
        if args and args[0] == "start":
            argv.append("--no-version-probe")
        env = dict(os.environ)
        env["DATABASE_URL"] = workspace["database_url"]
        env.pop("DEFAULT_MODEL", None)
        result = subprocess.run(
            argv,
            cwd=workspace["path"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "rc": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    @keyword("Get Sidecar Session Id")
    def get_sidecar_session_id(self, workspace: dict) -> str:
        """Return the session_id recorded in the workspace sidecar.

        Raises:
            AssertionError: If no sidecar exists.
        """
        sidecar = Path(workspace["sidecar"])
        if not sidecar.exists():
            raise AssertionError(f"no sidecar at {sidecar}")
        return str(json.loads(sidecar.read_text())["session_id"])

    @keyword("Sidecar Should Not Exist")
    def sidecar_should_not_exist(self, workspace: dict) -> None:
        """Fail if the workspace sidecar file is still on disk."""
        sidecar = Path(workspace["sidecar"])
        if sidecar.exists():
            raise AssertionError(f"sidecar still present at {sidecar}")

    @keyword("Get Harness Row")
    def get_harness_row(self, workspace: dict, session_id: str) -> dict:
        """Fetch the agentic_harnesses row for ``session_id`` as a dict.

        Raises:
            AssertionError: If the row does not exist.
        """
        db = HarnessDatabase(database_url=workspace["database_url"])
        harness = db.get_harness(session_id)
        if harness is None:
            raise AssertionError(
                f"no agentic_harnesses row for session_id={session_id!r}"
            )
        return dataclasses.asdict(harness)

    @keyword("Get Makefile Session Id")
    def get_makefile_session_id(self, workspace: dict) -> str:
        """Run ``makefile_session_id()`` in a fresh process in the workspace.

        Mirrors exactly what the Makefile does to attach ``make robot``
        runs to an open harness session (Issue #411).
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from rfc.harness_cli import makefile_session_id; "
                "print(makefile_session_id())",
            ],
            cwd=workspace["path"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return result.stdout.strip()
