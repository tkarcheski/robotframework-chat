"""Live coding-agent runner for the agentic-coding suite.

Drives a coding-agent CLI against a scenario in an isolated git worktree,
normalizes its transcript into an :class:`~rfc.agent_run.AgentRun`, and surfaces
the same fields the fake and ollama runners produce so every existing tier:1
verifier re-applies unchanged.

The CLI-specific bits — the argv, the transcript parser, and the "is this CLI
installed?" probe — live behind a :class:`~rfc.harness_adapters.HarnessAdapter`
(Issue #172). ``LiveClaudeCodeRunner`` is now a thin driver parameterized by an
adapter: it owns only the harness-agnostic work (git worktree create/cleanup,
commit collection, changed-path tracking, redaction, ``AgentRun`` assembly) and
routes CLI I/O through the adapter. It defaults to :class:`ClaudeCodeAdapter`,
so the Claude Code path (and its tests) is unchanged; pass ``adapter=`` to drive
opencode or codex instead.

MVP scope, per the design decisions captured on Issue #288 (still in force):
  * Bash tool calls become :class:`AgentCommand` rows.
  * Clarifying questions are pulled from assistant text blocks (paragraphs
    ending in ``?`` with optional bullet/number/letter options under them).
  * End-of-run ``git status --porcelain`` populates ``changed_paths_after``
    on the *last* command only -- per-command tracking is a follow-up
    (decision 2d).
  * Commits come from ``git log origin/<base>..HEAD``.
  * PR-body capture via MCP is deferred -- ``run.pr`` is always ``None``
    in this MVP (decision 5c).
  * Every captured stdout/stderr tail is passed through :func:`redact`,
    which strips a known-secret regex list plus any values read from
    ``.env`` (decision 4b).

Process invocation is injectable via the ``invoker`` constructor argument
so tests never spawn a real subprocess.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from .agent_config import AgentConfig
from .agent_run import AgentCommand, AgentCommit, AgentRun
from .harness_adapters import (
    ClaudeCodeAdapter,
    ClaudeProcessResult,
    CodexAdapter,
    HarnessAdapter,
    OpenCodeAdapter,
    ProcessInvoker,
    _default_invoker,
    make_branch_name,
    parse_transcript,
    redact,
)

# Re-exported for backward compatibility: the primitives and helpers below moved
# to rfc.harness_adapters when the harness seam was extracted (Issue #172), but
# existing importers (and tests) still reach for them here.
__all__ = [
    "ClaudeCodeAdapter",
    "ClaudeProcessResult",
    "CodexAdapter",
    "HarnessAdapter",
    "LiveClaudeCodeRunner",
    "OpenCodeAdapter",
    "ProcessInvoker",
    "make_branch_name",
    "parse_transcript",
    "redact",
]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_env_values(env_file: Path) -> tuple[str, ...]:
    if not env_file.is_file():
        return ()
    values: list[str] = []
    for line in env_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        _, _, raw = stripped.partition("=")
        raw = raw.strip().strip("'\"")
        if raw:
            values.append(raw)
    return tuple(values)


@dataclass(frozen=True)
class _ScenarioTask:
    scenario_id: str
    task: str
    base_branch: str


def _load_scenario_task(scenario_dir: Path) -> _ScenarioTask:
    task_path = scenario_dir / "task.yaml"
    if not task_path.is_file():
        raise KeyError(f"No task.yaml under {scenario_dir}")
    raw = yaml.safe_load(task_path.read_text()) or {}
    missing = [k for k in ("scenario_id", "task", "base_branch") if k not in raw]
    if missing:
        raise ValueError(f"{task_path} missing keys: {missing}")
    return _ScenarioTask(
        scenario_id=str(raw["scenario_id"]),
        task=str(raw["task"]),
        base_branch=str(raw["base_branch"]),
    )


class LiveClaudeCodeRunner:
    """Run a live coding-agent CLI against a scenario.

    Despite the historical name, the runner is harness-agnostic: it drives
    whatever :class:`~rfc.harness_adapters.HarnessAdapter` it is given and
    defaults to :class:`ClaudeCodeAdapter`.

    Constructor wiring:

      * ``config`` -- :class:`AgentConfig` with ``runner=live``.
      * ``scenarios_root`` -- directory containing ``<scenario_id>/task.yaml``.
      * ``invoker`` -- subprocess shim; tests inject a stub.
      * ``workspace_root`` -- where per-scenario worktrees are created.
        If unset, a fresh tempdir is used and removed on cleanup.
      * ``repo_root`` -- repo to ``git worktree add`` from; defaults to
        the rfc checkout this module lives in.
      * ``claude_bin`` -- path to the ``claude`` CLI binary; used only to build
        the default :class:`ClaudeCodeAdapter` (ignored when ``adapter`` is
        passed).
      * ``env_file`` -- ``.env`` to read for redaction-only secret values;
        defaults to ``<repo_root>/.env``.
      * ``adapter`` -- the :class:`~rfc.harness_adapters.HarnessAdapter` to
        drive; defaults to :class:`ClaudeCodeAdapter`.
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        scenarios_root: Path,
        invoker: ProcessInvoker | None = None,
        workspace_root: Path | None = None,
        repo_root: Path | None = None,
        claude_bin: str = "claude",
        env_file: Path | None = None,
        adapter: HarnessAdapter | None = None,
    ) -> None:
        if config.runner != "live":
            raise ValueError(
                f"LiveClaudeCodeRunner requires runner=live, got {config.runner!r}"
            )
        self.config = config
        self.scenarios_root = scenarios_root
        self._invoker = invoker or _default_invoker
        self._workspace_root = workspace_root
        self.repo_root = repo_root or REPO_ROOT
        self.claude_bin = claude_bin
        self._adapter = adapter or ClaudeCodeAdapter(claude_bin=claude_bin)
        self._env_file = env_file if env_file is not None else (self.repo_root / ".env")

    def list_scenarios(self) -> list[str]:
        if not self.scenarios_root.exists():
            return []
        return sorted(
            child.name
            for child in self.scenarios_root.iterdir()
            if child.is_dir() and (child / "task.yaml").is_file()
        )

    def run(self, scenario_id: str) -> AgentRun:
        scenario_dir = self.scenarios_root / scenario_id
        task = _load_scenario_task(scenario_dir)
        secrets = _read_env_values(self._env_file)
        branch_name = make_branch_name(task.task, prefix=self._adapter.branch_prefix)
        workspace, owns_workspace = self._allocate_workspace(scenario_id)
        try:
            self._create_worktree(workspace, task.base_branch, branch_name)
            result = self._invoke_agent(workspace, task.task)
            commands, questions = self._adapter.parse_output(
                result.stdout, extra_secrets=secrets
            )
            commits = self._collect_commits(workspace, task.base_branch, secrets)
            changed = self._final_changed_paths(workspace)
            commands = _attach_changed_paths(commands, changed)
            return AgentRun(
                agent_id=self.config.id,
                scenario_id=scenario_id,
                task=task.task,
                base_branch=task.base_branch,
                branch_name=branch_name,
                commands=commands,
                questions=questions,
                commits=commits,
                pr=None,
                transcript_path=None,
            )
        finally:
            self._cleanup_worktree(workspace, owns_workspace=owns_workspace)

    def _allocate_workspace(self, scenario_id: str) -> tuple[Path, bool]:
        if self._workspace_root is not None:
            self._workspace_root.mkdir(parents=True, exist_ok=True)
            return self._workspace_root / scenario_id, False
        return Path(tempfile.mkdtemp(prefix=f"rfc-live-{scenario_id}-")), True

    def _create_worktree(
        self, workspace: Path, base_branch: str, branch_name: str
    ) -> None:
        if workspace.is_dir() and any(workspace.iterdir()):
            return
        if workspace.is_dir():
            workspace.rmdir()
        self._invoker(
            (
                "git",
                "worktree",
                "add",
                "-b",
                branch_name,
                str(workspace),
                f"origin/{base_branch}",
            ),
            self.repo_root,
            {},
            60,
        )
        workspace.mkdir(parents=True, exist_ok=True)

    def _invoke_agent(self, workspace: Path, task: str) -> ClaudeProcessResult:
        argv = tuple(self._adapter.build_argv(task, workspace))
        return self._invoker(
            argv,
            workspace,
            self._adapter.env_overrides(),
            self.config.timeout_seconds,
        )

    def _final_changed_paths(self, workspace: Path) -> tuple[str, ...]:
        result = self._invoker(
            ("git", "status", "--porcelain"),
            workspace,
            {},
            30,
        )
        paths: list[str] = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            paths.append(line[3:].strip())
        return tuple(paths)

    def _collect_commits(
        self,
        workspace: Path,
        base_branch: str,
        secrets: tuple[str, ...],
    ) -> tuple[AgentCommit, ...]:
        result = self._invoker(
            (
                "git",
                "log",
                "--format=%H%x1f%s%x1f%b%x1e",
                f"origin/{base_branch}..HEAD",
            ),
            workspace,
            {},
            30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ()
        commits: list[AgentCommit] = []
        for chunk in result.stdout.split("\x1e"):
            chunk = chunk.strip("\n").strip()
            if not chunk:
                continue
            parts = chunk.split("\x1f")
            if len(parts) < 2:
                continue
            sha = parts[0].strip()
            subject = parts[1].strip()
            message = parts[2].strip() if len(parts) > 2 else ""
            commits.append(
                AgentCommit(
                    sha=sha,
                    subject=redact(subject, extra_secrets=secrets),
                    message=redact(message, extra_secrets=secrets),
                    files_changed=self._files_for_commit(workspace, sha),
                )
            )
        return tuple(commits)

    def _files_for_commit(self, workspace: Path, sha: str) -> tuple[str, ...]:
        result = self._invoker(
            ("git", "show", "--name-only", "--format=", sha),
            workspace,
            {},
            30,
        )
        return tuple(p.strip() for p in result.stdout.splitlines() if p.strip())

    def _cleanup_worktree(self, workspace: Path, *, owns_workspace: bool) -> None:
        if not workspace.exists():
            return
        try:
            self._invoker(
                ("git", "worktree", "remove", "--force", str(workspace)),
                self.repo_root,
                {},
                30,
            )
        except Exception:
            # Best-effort: cleanup must not mask the run's own errors.
            pass
        if owns_workspace and workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)


def _attach_changed_paths(
    commands: tuple[AgentCommand, ...],
    changed: tuple[str, ...],
) -> tuple[AgentCommand, ...]:
    if not commands or not changed:
        return commands
    last = commands[-1]
    updated = AgentCommand(
        argv=last.argv,
        cwd=last.cwd,
        returncode=last.returncode,
        stdout_tail=last.stdout_tail,
        stderr_tail=last.stderr_tail,
        changed_paths_after=changed,
    )
    return (*commands[:-1], updated)
