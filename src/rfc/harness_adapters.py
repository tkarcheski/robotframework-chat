"""Harness adapters: the CLI-specific seam of the live agentic-coding runner.

A :class:`HarnessAdapter` isolates the parts of driving a coding-agent CLI that
differ per tool:

  * :meth:`~HarnessAdapter.build_argv` — the argv that launches the CLI headless
    against one task in a prepared workspace.
  * :meth:`~HarnessAdapter.parse_output` — normalize the CLI's transcript into
    the ``(commands, questions)`` pair every tier:1 verifier consumes.
  * :meth:`~HarnessAdapter.probe` — is the CLI installed and runnable here?

Everything harness-AGNOSTIC — the git worktree lifecycle, commit collection,
changed-path tracking, secret redaction, and final
:class:`~rfc.agent_run.AgentRun` assembly — stays in
:class:`~rfc.live_agent_runner.LiveClaudeCodeRunner`, which is now a thin driver
parameterized by an adapter.

Design note (seam boundary, re Issue #172): the #172 sketch wrote the protocol
as ``parse_output(raw) -> AgentRun``. The adapter instead returns the
CLI-derived ``(commands, questions)`` only. Commits, changed paths, the branch
name, and the run identifiers are harness-agnostic git/driver facts — deriving
them once in the driver keeps every adapter free of duplicated git logic and
preserves the existing :func:`parse_transcript` contract (and its tests)
verbatim. The driver assembles the ``AgentRun`` from the adapter's output plus
its own git observations.

Three adapters ship:

  * :class:`ClaudeCodeAdapter` — ``claude -p <task> --output-format stream-json
    --verbose``; :meth:`~ClaudeCodeAdapter.parse_output` delegates to the
    existing :func:`parse_transcript`, so the Claude Code path is byte-for-byte
    unchanged.
  * :class:`OpenCodeAdapter` — ``opencode run --format json <task>``, reusing a
    repo ``opencode.json`` (local Ollama, no external egress) via the
    ``OPENCODE_CONFIG`` env var. Parses opencode's JSON event stream.
  * :class:`CodexAdapter` — ``codex exec --json <task>``. The ``codex`` CLI is
    not installed on this box, so :meth:`~CodexAdapter.probe` returns ``False``
    and the adapter is skipped cleanly. The parser is written against codex's
    documented ``exec --json`` (JSONL) event format and is marked PENDING LIVE
    CONFORMANCE until the owner installs the CLI (Issue #172, owner decision 3).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .agent_run import AgentCommand, AgentQuestion
from .opencode_config import (
    _DEFAULT_OPENCODE_CONFIG,
    VerifiedLocalModel,
    assert_model_resolves_local,
    gate_config,
    load_opencode_config,
)

# ---------------------------------------------------------------------------
# Process-invocation primitives (shared by the driver and its adapters).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaudeProcessResult:
    """Result of running a single subprocess.

    Named for historical reasons (the Claude Code MVP); it is the generic
    invoker result every harness uses.
    """

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


# ---------------------------------------------------------------------------
# Redaction + text helpers.
# ---------------------------------------------------------------------------

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


def make_branch_name(task: str, *, prefix: str = "claude") -> str:
    """Return a contract-compliant branch name (``<prefix>/<slug>-<5chars>``).

    ``prefix`` defaults to ``claude`` so the Claude Code path is unchanged; each
    adapter passes its own :attr:`HarnessAdapter.branch_prefix` so an opencode
    run lands on ``opencode/…`` and a codex run on ``codex/…``.
    """
    return f"{prefix}/{_slugify(task)}-{uuid.uuid4().hex[:5]}"


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


# The normalized, CLI-format-specific artifact every adapter emits: the ordered
# commands the agent ran and the clarifying questions it asked. The driver folds
# these into a full AgentRun with its own git-derived commits and changed paths.
ParsedOutput = tuple[tuple[AgentCommand, ...], tuple[AgentQuestion, ...]]


# ---------------------------------------------------------------------------
# Claude Code: stream-json transcript parser (unchanged behaviour).
# ---------------------------------------------------------------------------


def parse_transcript(
    stdout: str,
    *,
    extra_secrets: tuple[str, ...] = (),
) -> ParsedOutput:
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


# ---------------------------------------------------------------------------
# The adapter protocol.
# ---------------------------------------------------------------------------


@runtime_checkable
class HarnessAdapter(Protocol):
    """CLI-specific seam for the live agentic-coding runner.

    Attributes:
      * ``name`` — taxonomy name, one of :data:`rfc.harness_cli.TOOLS`.
      * ``branch_prefix`` — git branch namespace for this harness's runs.
    """

    name: str
    branch_prefix: str

    def build_argv(self, task: str, workspace: Path) -> list[str]:
        """The argv that runs this CLI headless against ``task`` in ``workspace``."""
        ...

    def env_overrides(self) -> dict[str, str]:
        """Environment overrides applied only to the agent invocation."""
        ...

    def parse_output(
        self, raw: str, *, extra_secrets: tuple[str, ...] = ()
    ) -> ParsedOutput:
        """Normalize this CLI's transcript into ``(commands, questions)``."""
        ...

    def probe(self) -> bool:
        """True when this CLI is present and runnable in the current environment."""
        ...


def _probe_binary(binary: str, *, version_flag: str = "--version") -> bool:
    """True when ``binary`` is on PATH and ``binary <version_flag>`` exits 0.

    Environment detection, deliberately outside the injectable invoker: probing
    is about whether the host can run the CLI at all, so it shells out directly
    and treats any failure (missing binary, timeout, nonzero exit) as absent.
    """
    if shutil.which(binary) is None:
        return False
    try:
        result = subprocess.run(
            [binary, version_flag],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


# ---------------------------------------------------------------------------
# ClaudeCodeAdapter.
# ---------------------------------------------------------------------------


class ClaudeCodeAdapter:
    """Drive the Claude Code CLI (``claude -p … --output-format stream-json``)."""

    name = "claude-code"
    branch_prefix = "claude"

    def __init__(self, *, claude_bin: str = "claude") -> None:
        self.claude_bin = claude_bin

    def build_argv(self, task: str, workspace: Path) -> list[str]:
        return [
            self.claude_bin,
            "-p",
            task,
            "--output-format",
            "stream-json",
            "--verbose",
        ]

    def env_overrides(self) -> dict[str, str]:
        return {}

    def parse_output(
        self, raw: str, *, extra_secrets: tuple[str, ...] = ()
    ) -> ParsedOutput:
        return parse_transcript(raw, extra_secrets=extra_secrets)

    def probe(self) -> bool:
        return _probe_binary(self.claude_bin)


# ---------------------------------------------------------------------------
# OpenCodeAdapter.
# ---------------------------------------------------------------------------


def parse_opencode_events(
    raw: str,
    *,
    extra_secrets: tuple[str, ...] = (),
) -> ParsedOutput:
    """Parse an ``opencode run --format json`` event stream.

    opencode emits one JSON object per line. Each carries a ``part``; the parts
    this normalizer reads are:

      * bash tool calls — ``part.type == "tool"`` with ``part.tool == "bash"``.
        The terminal ``part.state`` holds ``input.command`` (the shell string),
        a ``status`` of ``completed`` / ``error``, and the captured ``output``
        (or ``error`` text). Each becomes one :class:`AgentCommand` wrapped as
        ``("bash", "-lc", <command>)`` so the tier:1 shell verifiers apply
        identically to the Claude Code path. A non-terminal state (``running``,
        ``pending``) is skipped — the run is captured after it finishes.
      * assistant text — ``part.type == "text"`` — scanned for clarifying
        questions.
    """
    commands: list[AgentCommand] = []
    questions: list[AgentQuestion] = []

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")

        if ptype == "tool" and part.get("tool") == "bash":
            state = part.get("state")
            if not isinstance(state, dict):
                continue
            status = state.get("status")
            command = (state.get("input") or {}).get("command")
            if not isinstance(command, str) or not command:
                continue
            if status == "completed":
                returncode = 0
                output = str(state.get("output") or "")
            elif status == "error":
                returncode = 1
                output = str(state.get("error") or state.get("output") or "")
            else:
                # running / pending — not a terminal result; skip.
                continue
            commands.append(
                AgentCommand(
                    argv=("bash", "-lc", command),
                    returncode=returncode,
                    stdout_tail=redact(_tail(output), extra_secrets=extra_secrets),
                    stderr_tail="",
                )
            )
        elif ptype == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                questions.extend(_extract_questions(text))

    return tuple(commands), tuple(questions)


class OpenCodeAdapter:
    """Drive the opencode CLI headless (``opencode run --format json <task>``).

    ``config_path`` is exported as ``OPENCODE_CONFIG`` so a run reuses the repo
    ``opencode.json`` (local Ollama, no external egress). ``model`` overrides
    the model via ``--model provider/model`` when the config's default is not
    wanted.

    #278: this adapter is the layer that materializes the opencode config for a
    run, so it is the durable home of the Tier-A comparability gate. Any consumer
    can ask :meth:`verify_local_model` whether this run's model resolves to a
    declared-local provider (getting back the :class:`VerifiedLocalModel` token a
    Tier-A ``ComparisonRow`` requires) instead of re-implementing the check. When
    ``require_local_comparability`` is set, :meth:`env_overrides` runs that gate
    before the config is materialized, so a run using this config CANNOT proceed
    with a non-local model even if the runner never calls the gate itself.
    """

    name = "opencode"
    branch_prefix = "opencode"

    def __init__(
        self,
        *,
        opencode_bin: str = "opencode",
        config_path: Path | None = None,
        model: str | None = None,
        require_local_comparability: bool = False,
    ) -> None:
        self.opencode_bin = opencode_bin
        self.config_path = config_path
        self.model = model
        self.require_local_comparability = require_local_comparability

    def build_argv(self, task: str, workspace: Path) -> list[str]:
        argv = [self.opencode_bin, "run", "--format", "json"]
        if self.model:
            argv += ["--model", self.model]
        argv.append(task)
        return argv

    def verify_local_model(self) -> VerifiedLocalModel:
        """Gate this adapter's opencode config, returning the Tier-A token (#278).

        The run's model — the ``--model`` override if set, else the config's pinned
        default — must resolve to a DECLARED LOCAL provider (#191/#273), or this
        raises :class:`~rfc.opencode_config.ComparabilityError`. Returns the
        gate-minted :class:`VerifiedLocalModel`, the capability a Tier-A
        ``ComparisonRow`` requires. An override is resolved against the SAME
        config, so it cannot smuggle a remote model past the config default. This
        is the adapter-layer home of the selected-model-resolves-local check: a
        second comparison runner calls this one method rather than re-deriving the
        gate procedurally.
        """
        path = self.config_path or _DEFAULT_OPENCODE_CONFIG
        config = load_opencode_config(path)
        if self.model:
            return assert_model_resolves_local(
                self.model, config, source=f"opencode --model override ({path})"
            )
        return gate_config(config, source=f"opencode.json ({path})")

    def env_overrides(self) -> dict[str, str]:
        # #278: when armed for a Tier-A comparison run, fail closed BEFORE the
        # config materializes, so a non-local model can never reach the CLI. Opt-in
        # (default off) so the general live-runner path over arbitrary configs is
        # unchanged.
        if self.require_local_comparability:
            self.verify_local_model()
        if self.config_path is not None:
            return {"OPENCODE_CONFIG": str(self.config_path)}
        return {}

    def parse_output(
        self, raw: str, *, extra_secrets: tuple[str, ...] = ()
    ) -> ParsedOutput:
        return parse_opencode_events(raw, extra_secrets=extra_secrets)

    def probe(self) -> bool:
        return _probe_binary(self.opencode_bin)


# ---------------------------------------------------------------------------
# CodexAdapter (PENDING LIVE CONFORMANCE — codex CLI not installed here).
# ---------------------------------------------------------------------------


def parse_codex_events(
    raw: str,
    *,
    extra_secrets: tuple[str, ...] = (),
) -> ParsedOutput:
    """Parse a ``codex exec --json`` event stream (JSONL).

    PENDING LIVE CONFORMANCE: written against codex's documented experimental
    ``exec --json`` format, not yet verified against a real binary (the CLI is
    not installed on this box). Each line is a JSON object; the events read are
    a ``msg`` envelope (``{"id": …, "msg": {"type": …}}``) — codex's shape —
    falling back to a flat top-level object:

      * ``exec_command_begin`` — ``command`` (an argv array) keyed by
        ``call_id``.
      * ``exec_command_end`` — ``stdout`` / ``stderr`` / ``exit_code`` paired
        back to its begin by ``call_id``, yielding one :class:`AgentCommand`.
      * ``agent_message`` — assistant text (``message``/``text``), scanned for
        clarifying questions.
    """
    commands: list[AgentCommand] = []
    questions: list[AgentQuestion] = []
    pending: dict[str, tuple[str, ...]] = {}

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        # codex wraps the payload in a "msg" envelope; tolerate a flat object.
        msg = event.get("msg")
        if not isinstance(msg, dict):
            msg = event
        mtype = msg.get("type")

        if mtype == "exec_command_begin":
            call_id = str(msg.get("call_id", ""))
            command = msg.get("command")
            if isinstance(command, list) and command:
                pending[call_id] = tuple(str(part) for part in command)
            elif isinstance(command, str) and command:
                pending[call_id] = ("bash", "-lc", command)
        elif mtype == "exec_command_end":
            call_id = str(msg.get("call_id", ""))
            argv = pending.pop(call_id, None)
            if argv is None:
                continue
            stdout = str(msg.get("stdout") or "")
            stderr = str(msg.get("stderr") or "")
            exit_code = msg.get("exit_code")
            returncode = int(exit_code) if isinstance(exit_code, int) else 0
            commands.append(
                AgentCommand(
                    argv=argv,
                    returncode=returncode,
                    stdout_tail=redact(_tail(stdout), extra_secrets=extra_secrets),
                    stderr_tail=redact(_tail(stderr), extra_secrets=extra_secrets),
                )
            )
        elif mtype == "agent_message":
            text = msg.get("message")
            if not isinstance(text, str):
                text = msg.get("text")
            if isinstance(text, str) and text:
                questions.extend(_extract_questions(text))

    return tuple(commands), tuple(questions)


class CodexAdapter:
    """Drive the Codex CLI headless (``codex exec --json <task>``).

    PENDING LIVE CONFORMANCE: the ``codex`` binary is not installed here, so
    :meth:`probe` returns ``False`` and the driver / tests skip it cleanly. The
    argv and parser follow codex's documented ``exec --json`` format; once the
    owner installs the CLI (and OpenAI auth) the codex path joins with no code
    change (Issue #172, owner decision 3).
    """

    name = "codex"
    branch_prefix = "codex"

    def __init__(self, *, codex_bin: str = "codex") -> None:
        self.codex_bin = codex_bin

    def build_argv(self, task: str, workspace: Path) -> list[str]:
        return [self.codex_bin, "exec", "--json", task]

    def env_overrides(self) -> dict[str, str]:
        return {}

    def parse_output(
        self, raw: str, *, extra_secrets: tuple[str, ...] = ()
    ) -> ParsedOutput:
        return parse_codex_events(raw, extra_secrets=extra_secrets)

    def probe(self) -> bool:
        return _probe_binary(self.codex_bin)


# Adapter registry keyed by taxonomy name (:data:`rfc.harness_cli.TOOLS`).
ADAPTERS: dict[str, Callable[[], HarnessAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "opencode": OpenCodeAdapter,
    "codex": CodexAdapter,
}


def get_adapter(name: str) -> HarnessAdapter:
    """Construct the default adapter for a taxonomy ``name``.

    Raises :class:`KeyError` for an unknown harness name.
    """
    if name not in ADAPTERS:
        raise KeyError(f"Unknown harness {name!r}; known harnesses: {sorted(ADAPTERS)}")
    return ADAPTERS[name]()
