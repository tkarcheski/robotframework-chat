"""Robot Framework keyword library: run a coding-agent task inside a harness session.

:class:`HarnessKeywords` is the public keyword surface that drives the
multi-harness runner (the :class:`~rfc.harness_adapters.HarnessAdapter` seam from
#172) from Robot Framework and the RSI loop, while bracketing every run in an
``agentic_harnesses`` session so it lands in the DB for transparency (#173).

Lifecycle, one keyword per stage:

  1. `Create Harness Workspace` — turn a directory into a throwaway git repo with
     its own sqlite database (the session's home).
  2. `Start Harness Session  tool=  workspace=  model=` — open a session via the
     ``rfc harness start`` spine (writes the ``agentic_harnesses`` row and the
     per-worktree sidecar), selecting the :class:`HarnessAdapter` for ``tool``.
  3. `Run Agent Task  task=  base_branch=` — drive the selected adapter headless
     against ``task`` in an isolated git worktree, normalizing the CLI transcript
     into an :class:`~rfc.agent_run.AgentRun` — the artifact every
     :mod:`rfc.agent_verifiers` assertion consumes, so a single conformance suite
     can grade every harness with the same checks.
  4. `Get Agent Transcript` — return the :class:`AgentRun` captured by the last
     `Run Agent Task`, for verifier keywords / inspection.
  5. `End Harness Session  outcome=` — close the session row and remove the sidecar.

`Harness Is Available  tool=` probes whether a harness CLI is installed, so a
conformance suite can skip an absent one cleanly (``codex`` is absent by
default and skips with no suite change).

The session bracket reuses :mod:`rfc.harness_cli` verbatim by shelling out to
``python -m rfc.harness_cli harness start|end`` inside the workspace — the same
cross-process contract :mod:`rfc.harness_cli_kw` and :mod:`rfc.harness_listener_kw`
rely on — so the row, sidecar, and plugin/skill snapshots are created exactly as
in production. Only the agent invocation is injectable (``invoker=``), so unit
tests replay a recorded transcript without spawning a real agent, mirroring
:class:`~rfc.live_agent_runner.LiveClaudeCodeRunner`.

Used by ``robot/40__tier4/harness_matrix/harness_matrix.robot`` (tier:4,
verify:python — real subprocesses, probe- and cost-gated).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from robot.api.deco import keyword  # type: ignore[import-untyped]

from .agent_config import AgentConfig
from .agent_run import AgentRun
from .git_metadata import _git_command
from .harness_adapters import (
    ADAPTERS,
    HarnessAdapter,
    OpenCodeAdapter,
    ProcessInvoker,
    get_adapter,
)
from .live_agent_runner import LiveClaudeCodeRunner

_SIDECAR_NAME = "rfc-harness-session.json"
_SCENARIO_ID = "harness_matrix_task"
_VALID_OUTCOMES = ("success", "partial", "failed")

# Repo ``opencode.json`` (local Ollama, no external egress) exported as
# OPENCODE_CONFIG for opencode runs. Lives at the core/ root, two parents up
# from this package (src/rfc/ -> src/ -> core/).
_DEFAULT_OPENCODE_CONFIG = (
    Path(__file__).resolve().parent.parent.parent / "opencode.json"
)


class HarnessKeywords:
    """Robot-facing keywords to run a coding-agent task inside a harness session."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(
        self,
        invoker: ProcessInvoker | None = None,
        repo_root: str | Path | None = None,
        opencode_config: str | Path | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        """Wire the library.

        Args:
            invoker: Subprocess shim for the *agent* invocation. ``None`` (the
                default) uses the real subprocess path; tests inject a stub that
                replays a recorded transcript.
            repo_root: Repo to ``git worktree add`` the agent's isolated
                workspace from. ``None`` defaults to the rfc checkout (the
                production path).
            opencode_config: ``opencode.json`` exported as ``OPENCODE_CONFIG``
                for opencode runs. ``None`` uses the repo default.
            timeout_seconds: Per-agent-run wall-clock budget.
        """
        self._invoker = invoker
        self._repo_root = Path(repo_root) if repo_root else None
        self._opencode_config = (
            Path(opencode_config) if opencode_config else _DEFAULT_OPENCODE_CONFIG
        )
        self._timeout_seconds = int(timeout_seconds)
        self._session: dict | None = None
        self._run: AgentRun | None = None

    # ------------------------------------------------------------------
    # Workspace + probe helpers.
    # ------------------------------------------------------------------

    @keyword("Create Harness Workspace")
    def create_harness_workspace(self, root: str) -> dict:
        """Turn ``root`` into a throwaway git repo with its own sqlite database.

        Args:
            root: An existing directory to initialise.

        Returns:
            A workspace dict with ``path`` and ``database_url`` keys, passed to
            `Start Harness Session`.
        """
        root_path = Path(root)
        subprocess.run(["git", "init", "-q"], cwd=root_path, check=True, timeout=60)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=harness@agents.rfc",
                "-c",
                "user.name=harness",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "root",
            ],
            cwd=root_path,
            check=True,
            timeout=60,
        )
        return {
            "path": str(root_path),
            "database_url": f"sqlite:///{root_path / 'harness.db'}",
        }

    @keyword("Harness Is Available")
    def harness_is_available(self, tool: str) -> bool:
        """Return whether the harness CLI for ``tool`` is installed and runnable.

        Probe-only: it never spends tokens, so a suite can ``Skip If`` an absent
        harness (e.g. ``codex``) cleanly.
        """
        if tool not in ADAPTERS:
            raise ValueError(f"unknown harness {tool!r}; known: {sorted(ADAPTERS)}")
        return get_adapter(tool).probe()

    # ------------------------------------------------------------------
    # Session lifecycle.
    # ------------------------------------------------------------------

    @keyword("Start Harness Session")
    def start_harness_session(
        self, tool: str, workspace: str, model: str = "", database_url: str = ""
    ) -> dict:
        """Open a harness session bracketing subsequent runs.

        Runs ``rfc harness start --tool <tool>`` inside ``workspace`` (a git
        repo), writing the ``agentic_harnesses`` row and the sidecar. The
        selected :class:`HarnessAdapter` — with ``model`` applied where the CLI
        takes a model override (opencode) — drives the next `Run Agent Task`.

        Args:
            tool: One of :data:`rfc.harness_cli.TOOLS`
                (``claude-code`` / ``opencode`` / ``codex``).
            workspace: Path to the session's git repo (see
                `Create Harness Workspace`).
            model: Optional model id override (e.g. ``ollama/qwen3-coder:30b``).
            database_url: Override for ``DATABASE_URL``; defaults to the env var.

        Returns:
            A session dict (``session_id``, ``tool``, ``workspace``,
            ``database_url``, ``model``).
        """
        if tool not in ADAPTERS:
            raise ValueError(f"unknown harness {tool!r}; known: {sorted(ADAPTERS)}")
        db_url = database_url or os.environ.get("DATABASE_URL", "")
        if not db_url:
            raise ValueError(
                "no database configured: pass database_url= or set DATABASE_URL "
                "(the agentic_harnesses row is the point of a harness session)"
            )
        workspace_path = Path(workspace)
        argv = [
            sys.executable,
            "-m",
            "rfc.harness_cli",
            "harness",
            "start",
            "--tool",
            tool,
            "--database-url",
            db_url,
            "--no-version-probe",
        ]
        if model:
            argv += ["--model", model]
        result = subprocess.run(
            argv,
            cwd=str(workspace_path),
            env=self._subprocess_env(db_url),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"`rfc harness start` failed (rc={result.returncode}): "
                f"{result.stderr.strip()}"
            )
        sidecar = self._sidecar_path(workspace_path)
        session_id = str(json.loads(sidecar.read_text())["session_id"])
        self._session = {
            "session_id": session_id,
            "tool": tool,
            "workspace": str(workspace_path),
            "database_url": db_url,
            "model": model,
        }
        self._run = None
        return dict(self._session)

    @keyword("Run Agent Task")
    def run_agent_task(self, task: str, base_branch: str = "main") -> AgentRun:
        """Run ``task`` under the active session's harness; capture the AgentRun.

        Writes a one-off ``task.yaml`` scenario, drives the session's
        :class:`HarnessAdapter` through a
        :class:`~rfc.live_agent_runner.LiveClaudeCodeRunner` against an isolated
        worktree of ``base_branch``, and returns the normalized
        :class:`AgentRun`. The run is retained for `Get Agent Transcript`.

        Args:
            task: The natural-language coding task for the agent.
            base_branch: The branch the agent's isolated worktree forks from.

        Returns:
            The :class:`AgentRun` — every :mod:`rfc.agent_verifiers` assertion
            applies to it identically, regardless of which harness produced it.
        """
        session = self._require_session()
        workspace = Path(session["workspace"])
        adapter = self._build_adapter(session["tool"], session["model"])

        scenarios_root = workspace / ".rfc-harness-scenarios"
        scenario_dir = scenarios_root / _SCENARIO_ID
        scenario_dir.mkdir(parents=True, exist_ok=True)
        (scenario_dir / "task.yaml").write_text(
            yaml.safe_dump(
                {
                    "scenario_id": _SCENARIO_ID,
                    "task": task,
                    "base_branch": base_branch,
                }
            )
        )

        config = AgentConfig(
            id=session["tool"], runner="live", timeout_seconds=self._timeout_seconds
        )
        runner = LiveClaudeCodeRunner(
            config=config,
            scenarios_root=scenarios_root,
            invoker=self._invoker,
            workspace_root=workspace / ".rfc-harness-worktrees",
            repo_root=self._repo_root,
            adapter=adapter,
        )
        run = runner.run(_SCENARIO_ID)
        self._run = run
        return run

    @keyword("Get Agent Transcript")
    def get_agent_transcript(self) -> AgentRun:
        """Return the :class:`AgentRun` from the last `Run Agent Task`."""
        if self._run is None:
            raise AssertionError("no agent run captured; call 'Run Agent Task' first")
        return self._run

    @keyword("End Harness Session")
    def end_harness_session(self, outcome: str = "success") -> dict:
        """Close the active session row and remove its sidecar.

        Args:
            outcome: One of ``success`` / ``partial`` / ``failed``.

        Returns:
            The session dict that was closed.
        """
        if outcome not in _VALID_OUTCOMES:
            raise ValueError(
                f"invalid outcome {outcome!r}; expected one of {_VALID_OUTCOMES}"
            )
        session = self._require_session()
        argv = [
            sys.executable,
            "-m",
            "rfc.harness_cli",
            "harness",
            "end",
            "--outcome",
            outcome,
            "--database-url",
            session["database_url"],
        ]
        result = subprocess.run(
            argv,
            cwd=session["workspace"],
            env=self._subprocess_env(session["database_url"]),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"`rfc harness end` failed (rc={result.returncode}): "
                f"{result.stderr.strip()}"
            )
        ended = dict(session)
        self._session = None
        self._run = None
        return ended

    # ------------------------------------------------------------------

    def _build_adapter(self, tool: str, model: str) -> HarnessAdapter:
        """The adapter for ``tool``, applying ``model`` where the CLI takes it.

        Only opencode wires a config + model (the repo ``opencode.json`` keeps
        the run on local Ollama with no external egress; #191 tracks fuller
        provider wiring). claude-code and codex take no model override here.
        """
        if tool == "opencode":
            config_path = (
                self._opencode_config
                if self._opencode_config and self._opencode_config.exists()
                else None
            )
            return OpenCodeAdapter(model=model or None, config_path=config_path)
        return get_adapter(tool)

    @staticmethod
    def _sidecar_path(workspace: Path) -> Path:
        """Resolve the harness sidecar inside ``workspace``'s real git dir (#386).

        ``rfc harness start`` writes the sidecar via
        ``git rev-parse --absolute-git-dir`` (:func:`rfc.harness_cli._sidecar_path`),
        so the reader must resolve it the SAME way instead of assuming
        ``<workspace>/.git`` is a directory. In a git WORKTREE workspace ``.git``
        is a gitdir-*pointer file*, not a directory, and the real sidecar lives
        under ``<main-checkout>/.git/worktrees/<name>/`` — reading
        ``<workspace>/.git/…`` there breaks the two halves of one contract apart
        (``start`` writes the row + sidecar, then the keyword can never read it).
        """
        git_dir = _git_command("-C", str(workspace), "rev-parse", "--absolute-git-dir")
        if not git_dir:
            raise AssertionError(f"{workspace} is not inside a git repository")
        return Path(git_dir) / _SIDECAR_NAME

    def _require_session(self) -> dict:
        if self._session is None:
            raise AssertionError(
                "no active harness session; call 'Start Harness Session' first"
            )
        return self._session

    @staticmethod
    def _subprocess_env(database_url: str) -> dict[str, str]:
        """Env for the harness_cli subprocess: workspace DB, no session leaks."""
        env = dict(os.environ)
        env["DATABASE_URL"] = database_url
        # Never let a parent session/model bleed into the workspace bracket.
        env.pop("DEFAULT_MODEL", None)
        env.pop("SESSION_ID", None)
        return env
