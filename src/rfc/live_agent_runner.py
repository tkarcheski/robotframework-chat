"""Live Claude Code CLI runner for the agentic-coding suite.

Drives ``claude -p`` against a scenario in an isolated git worktree, parses
the stream-json transcript into an :class:`~rfc.agent_run.AgentRun`, and
surfaces the same fields the fake and ollama runners produce so every
existing tier:1 verifier re-applies unchanged.

MVP scope, per the design decisions captured on Issue #288:
  * Bash tool_use entries become :class:`AgentCommand` rows, paired with
    their tool_result by ``tool_use_id``.
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

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .agent_config import AgentConfig
from .agent_run import AgentCommand, AgentCommit, AgentQuestion, AgentRun

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
    re.compile(r"xoxb-[A-Za-z0-9-]+"),
)

_REDACTED = "[REDACTED]"
_TAIL_LIMIT = 4000
_BRANCH_SLUG_RE = re.compile(r"[^a-z0-9]+")
_OPTION_RE = re.compile(r"^\s*(?:[-*]|\d+\.|\(?[a-d]\))\s*(.+)$")


@dataclass(frozen=True)
class ClaudeProcessResult:
    """Result of running a single subprocess."""

    returncode: int
    stdout: str
    stderr: str


ProcessInvoker = Callable[
    [tuple[str, ...], Path, dict[str, str], int], ClaudeProcessResult
]


def _default_invoker(
    argv: tuple[str, ...],
    cwd: Path,
    env_overrides: dict[str, str],
    timeout: int,
) -> ClaudeProcessResult:
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(
        list(argv),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return ClaudeProcessResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def redact(text: str, *, extra_secrets: tuple[str, ...] = ()) -> str:
    """Strip known secrets and any explicit ``extra_secrets`` from ``text``."""
    if not text:
        return text
    out = text
    for secret in extra_secrets:
        if secret:
            out = out.replace(secret, _REDACTED)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


def _tail(text: str, limit: int = _TAIL_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _slugify(text: str) -> str:
    cleaned = _BRANCH_SLUG_RE.sub("-", text.lower()).strip("-")
    return cleaned[:40] or "task"


def make_branch_name(task: str) -> str:
    """Return a contract-compliant branch name (``claude/<slug>-<5chars>``)."""
    return f"claude/{_slugify(task)}-{uuid.uuid4().hex[:5]}"


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


def _extract_tool_result_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text is not None:
                    parts.append(str(text))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _extract_questions(text: str) -> list[AgentQuestion]:
    """Pull clarifying questions from one assistant text block.

    Heuristic: split on blank lines, treat any paragraph whose first
    sentence ends with ``?`` as a question; subsequent bullet/numbered/
    letter-prefixed lines become its options.
    """
    questions: list[AgentQuestion] = []
    for paragraph in re.split(r"\n\s*\n", text):
        lines = paragraph.splitlines()
        q_text: str | None = None
        option_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if q_text is None:
                if stripped.endswith("?") and len(stripped) > 1:
                    q_text = stripped
                continue
            match = _OPTION_RE.match(line)
            if match:
                option_lines.append(match.group(1).strip())
        if q_text:
            questions.append(AgentQuestion(text=q_text, options=tuple(option_lines)))
    return questions


def parse_transcript(
    stdout: str,
    *,
    extra_secrets: tuple[str, ...] = (),
) -> tuple[tuple[AgentCommand, ...], tuple[AgentQuestion, ...]]:
    """Parse a Claude Code stream-json transcript.

    Returns ``(commands, questions)``. Every Bash ``tool_use`` block paired
    with its ``tool_result`` becomes one :class:`AgentCommand`. Each
    assistant text block is scanned for clarifying questions.

    All stdout text captured into ``stdout_tail`` is passed through
    :func:`redact` with ``extra_secrets`` so .env values can't leak.
    """
    commands: list[AgentCommand] = []
    questions: list[AgentQuestion] = []
    pending: dict[str, str] = {}

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        etype = event.get("type")
        if etype == "assistant":
            for block in (event.get("message") or {}).get("content", []) or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use" and block.get("name") == "Bash":
                    cmd = (block.get("input") or {}).get("command")
                    if isinstance(cmd, str) and cmd:
                        pending[str(block.get("id", ""))] = cmd
                elif btype == "text":
                    questions.extend(_extract_questions(str(block.get("text") or "")))
        elif etype == "user":
            for block in (event.get("message") or {}).get("content", []) or []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool_id = str(block.get("tool_use_id", ""))
                cmd = pending.pop(tool_id, None)
                if cmd is None:
                    continue
                result_text = _extract_tool_result_text(block.get("content"))
                is_error = bool(block.get("is_error", False))
                commands.append(
                    AgentCommand(
                        argv=("bash", "-lc", cmd),
                        returncode=1 if is_error else 0,
                        stdout_tail=redact(
                            _tail(result_text), extra_secrets=extra_secrets
                        ),
                        stderr_tail="",
                    )
                )

    return tuple(commands), tuple(questions)


class LiveClaudeCodeRunner:
    """Run the live Claude Code CLI against a scenario.

    Constructor wiring:

      * ``config`` -- :class:`AgentConfig` with ``runner=live``.
      * ``scenarios_root`` -- directory containing ``<scenario_id>/task.yaml``.
      * ``invoker`` -- subprocess shim; tests inject a stub.
      * ``workspace_root`` -- where per-scenario worktrees are created.
        If unset, a fresh tempdir is used and removed on cleanup.
      * ``repo_root`` -- repo to ``git worktree add`` from; defaults to
        the rfc checkout this module lives in.
      * ``claude_bin`` -- path to the ``claude`` CLI binary.
      * ``env_file`` -- ``.env`` to read for redaction-only secret values;
        defaults to ``<repo_root>/.env``.
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
        branch_name = make_branch_name(task.task)
        workspace, owns_workspace = self._allocate_workspace(scenario_id)
        try:
            self._create_worktree(workspace, task.base_branch, branch_name)
            claude_result = self._invoke_claude(workspace, task.task)
            commands, questions = parse_transcript(
                claude_result.stdout, extra_secrets=secrets
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

    def _invoke_claude(self, workspace: Path, task: str) -> ClaudeProcessResult:
        argv = (
            self.claude_bin,
            "-p",
            task,
            "--output-format",
            "stream-json",
            "--verbose",
        )
        return self._invoker(argv, workspace, {}, self.config.timeout_seconds)

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
