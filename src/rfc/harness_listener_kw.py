"""Robot Framework keyword library driving the AgenticHarnessListener
end-to-end (Issue #431, merged PR #416).

Workflow per test:

1. ``Create Listener Workspace`` — throwaway git repo + sqlite database.
2. ``Start Harness Session`` — real ``rfc harness start`` subprocess, so
   the sidecar and the ``agentic_harnesses`` row the listener's FK guard
   (#419) requires both exist.
3. ``Write Inner Suite`` — generate a minimal Robot suite whose tests emit
   ``RFC_DATA:llm_metrics`` (and optionally ``RFC_DATA:score``) payloads.
4. ``Run Inner Suite`` — run that suite as a *separate OS process*
   (``python -m robot``) with the AgenticHarnessListener attached, exactly
   as the Makefile ``LISTENER`` var does.
5. ``Get Metric Rows`` — query ``agentic_metrics`` for the session_id and
   assert rows per executed test case.

No LLM is invoked: the inner tests emit synthetic Ollama-shaped metric
payloads, so the suite is hermetic and parallel-safe (tmpdirs only).

Used by ``robot/harness/test_agentic_harness_listener_integration.robot``
(tier:1, verify:python).
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rfc.harness_db import HarnessDatabase

_INNER_SUITE_NAME = "inner_suite.robot"

_METRICS_PAYLOAD = json.dumps(
    {
        "prompt_eval_count": 100,
        "eval_count": 40,
        "total_duration_ns": 2_500_000_000,
    }
)

_SUITE_HEADER = """\
*** Settings ***
Library    rfc.rfc_data

*** Test Cases ***
"""

_TEST_BODIES = {
    "metrics": [
        f"    Emit Rfc Data    llm_metrics    {_METRICS_PAYLOAD}",
    ],
    "metrics+score": [
        f"    Emit Rfc Data    llm_metrics    {_METRICS_PAYLOAD}",
        "    Emit Rfc Data    score    0.75",
    ],
    "silent": [
        "    No Operation",
    ],
}


class HarnessListenerRunner:
    """RF keyword library for end-to-end AgenticHarnessListener testing."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def create_listener_workspace(self, root: str) -> dict:
        """Initialise a throwaway git repo + sqlite DB under ``root``.

        Args:
            root: Existing directory to turn into a workspace.

        Returns:
            Dict with ``path`` and ``database_url`` keys, passed to every
            other keyword in this library.
        """
        root_path = Path(root)
        subprocess.run(["git", "init", "-q"], cwd=root_path, check=True)
        return {
            "path": str(root_path),
            "database_url": f"sqlite:///{root_path / 'harness.db'}",
        }

    def start_harness_session(self, workspace: dict) -> str:
        """Run ``rfc harness start`` in the workspace; return the session id.

        Uses a real subprocess so the sidecar and the ``agentic_harnesses``
        row are created exactly as in production.
        """
        subprocess.run(
            [
                sys.executable,
                "-m",
                "rfc.harness_cli",
                "harness",
                "start",
                "--tool",
                "claude-code",
                "--no-version-probe",
            ],
            cwd=workspace["path"],
            env=self._subprocess_env(workspace),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        sidecar = Path(workspace["path"]) / ".git" / "rfc-harness-session.json"
        return str(json.loads(sidecar.read_text())["session_id"])

    def write_inner_suite(self, workspace: dict, *test_specs: str) -> str:
        """Generate the inner Robot suite; one test case per spec.

        Args:
            workspace: Dict from `Create Listener Workspace`.
            test_specs: One of ``metrics`` (emits an llm_metrics payload),
                ``metrics+score`` (adds a grader score emission), or
                ``silent`` (emits nothing).

        Returns:
            Absolute path of the generated suite file.

        Raises:
            ValueError: On an unknown spec.
        """
        lines = [_SUITE_HEADER]
        for index, spec in enumerate(test_specs, start=1):
            body = _TEST_BODIES.get(spec)
            if body is None:
                raise ValueError(f"unknown test spec: {spec!r}")
            lines.append(f"Inner Test {index} ({spec})")
            lines.extend(body)
            lines.append("")
        suite_path = Path(workspace["path"]) / _INNER_SUITE_NAME
        suite_path.write_text("\n".join(lines))
        return str(suite_path)

    def run_inner_suite(
        self, workspace: dict, database_url: Optional[str] = None
    ) -> dict:
        """Run the inner suite in a fresh process with the listener attached.

        Args:
            workspace: Dict from `Create Listener Workspace`.
            database_url: Override for ``DATABASE_URL`` (e.g. an unreachable
                path for the skip-and-log negative test). Defaults to the
                workspace database.

        Returns:
            Dict with ``rc``, ``stdout`` and ``stderr`` keys.
        """
        env = self._subprocess_env(workspace)
        if database_url is not None:
            env["DATABASE_URL"] = database_url
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "robot",
                "--listener",
                "rfc.agentic_harness_listener.AgenticHarnessListener",
                "--outputdir",
                str(Path(workspace["path"]) / "robot-output"),
                _INNER_SUITE_NAME,
            ],
            cwd=workspace["path"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "rc": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def get_metric_rows(
        self, workspace: dict, session_id: str, metric_key: str = ""
    ) -> list[dict]:
        """Fetch ``agentic_metrics`` rows for ``session_id`` as dicts."""
        db = HarnessDatabase(database_url=workspace["database_url"])
        metrics = db.get_metrics(session_id, metric_key=metric_key)
        return [dataclasses.asdict(metric) for metric in metrics]

    def count_all_metric_rows(self, workspace: dict) -> int:
        """Return the total ``agentic_metrics`` row count for the workspace DB."""
        db = HarnessDatabase(database_url=workspace["database_url"])
        return db.get_table_row_count("agentic_metrics")

    def _subprocess_env(self, workspace: dict) -> dict:
        """Subprocess env pointing at the workspace DB, free of session leaks."""
        env = dict(os.environ)
        env["DATABASE_URL"] = workspace["database_url"]
        env.pop("HARNESS_DATABASE_URL", None)
        env.pop("SESSION_ID", None)
        env.pop("DEFAULT_MODEL", None)
        return env
