"""Normalized run artifact produced by any coding-agent adapter.

An :class:`AgentRun` is the single data structure every verifier consumes.
Live adapters capture one by running the agent; fake adapters load one from
a prerecorded YAML fixture. Keeping verifiers agnostic to the source makes
the agentic-coding suite reusable across Claude Code, Codex CLI, Gemini CLI,
and any future agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_SHELL_WRAPPERS: tuple[tuple[str, str], ...] = (
    ("bash", "-lc"),
    ("bash", "-c"),
    ("sh", "-lc"),
    ("sh", "-c"),
)


@dataclass(frozen=True)
class AgentCommand:
    """One command the agent ran."""

    argv: tuple[str, ...]
    cwd: str | None = None
    returncode: int = 0
    stdout_tail: str = ""
    stderr_tail: str = ""
    changed_paths_after: tuple[str, ...] = field(default_factory=tuple)

    def joined(self) -> str:
        return " ".join(self.argv)

    def inner_shell_command(self) -> str | None:
        """The inner command string of a shell-wrapper invocation, else ``None``.

        ``("bash", "-lc", "uv run pytest & git commit")`` returns
        ``"uv run pytest & git commit"``; a plain ``argv`` returns ``None``.
        Lets verifiers inspect raw shell syntax (e.g. a trailing background
        ``&``) without re-deriving the wrapper-detection logic.
        """
        for wrapper in _SHELL_WRAPPERS:
            if tuple(self.argv[: len(wrapper)]) == wrapper and len(self.argv) > len(
                wrapper
            ):
                return self.argv[len(wrapper)]
        return None

    def shell_subcommands(self) -> tuple[str, ...]:
        """Split a shell-wrapper invocation into its && / ; / || subcommands.

        Plain invocations return a single-element tuple of the joined argv.
        """
        return tuple(sub for _, sub in self.shell_subcommands_with_operators())

    def shell_subcommands_with_operators(
        self,
    ) -> tuple[tuple[str | None, str], ...]:
        """Like :meth:`shell_subcommands`, keeping the joining operator.

        Each element is ``(operator, subcommand)`` where ``operator`` is the
        separator BEFORE the subcommand (``"&&"``, ``";"``, ``"||"``, ``"|"``,
        ``"&"``) or ``None`` for the first one. Verifiers need the operator:
        ``A && B`` runs B only when A succeeded, ``A || B`` only when A FAILED,
        ``A; B`` regardless, and ``A | B`` exits with B's status (A's failure
        is hidden without ``pipefail``) — conflating them excuses commit-on-red
        (#503).

        A single ``A & B`` is a background list: per the Bash manual, the ``&``
        backgrounds A (it runs asynchronously and ``$?`` for the list is 0
        regardless of A's eventual outcome) and B runs immediately without
        waiting. So ``&`` is a list separator like ``;`` whose preceding
        command's status is discarded — without splitting it, ``pytest & git
        commit`` looks like one opaque subcommand and the ungated commit slips
        through the test gate (#503 round 8).

        Operator-alternation ordering matters: ``&&`` precedes the bare ``&``
        and ``\\|\\|`` precedes ``\\|`` so the two-character operators are never
        split into two single-character ones.
        """
        for wrapper in _SHELL_WRAPPERS:
            if tuple(self.argv[: len(wrapper)]) == wrapper and len(self.argv) > len(
                wrapper
            ):
                inner = self.argv[len(wrapper)]
                tokens = re.split(r"\s*(&&|&|;|\|\||\|)\s*", inner)
                result: list[tuple[str | None, str]] = []
                operator: str | None = None
                for token in tokens:
                    if token in ("&&", "&", ";", "||", "|"):
                        operator = token
                        continue
                    if token.strip():
                        result.append((operator, token.strip()))
                        operator = None
                return tuple(result)
        return ((None, self.joined()),)


@dataclass(frozen=True)
class AgentQuestion:
    """A clarifying question the agent asked."""

    text: str
    options: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_multiple_choice(self) -> bool:
        return len(self.options) >= 2


@dataclass(frozen=True)
class AgentCommit:
    """A commit produced during the run."""

    sha: str
    subject: str
    message: str = ""
    files_changed: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AgentPR:
    """A pull request prepared (not necessarily pushed) during the run."""

    title: str
    body: str


@dataclass(frozen=True)
class AgentRun:
    """Normalized record of one agent run against one scenario."""

    agent_id: str
    scenario_id: str
    task: str
    base_branch: str
    branch_name: str
    commands: tuple[AgentCommand, ...] = field(default_factory=tuple)
    questions: tuple[AgentQuestion, ...] = field(default_factory=tuple)
    commits: tuple[AgentCommit, ...] = field(default_factory=tuple)
    pr: AgentPR | None = None
    transcript_path: str | None = None

    def first_change_under(self, prefix: str) -> int | None:
        """Return the index of the first command whose changed paths touch ``prefix``."""
        for idx, cmd in enumerate(self.commands):
            for path in cmd.changed_paths_after:
                if path.startswith(prefix):
                    return idx
        return None


_REQUIRED_KEYS = (
    "agent_id",
    "scenario_id",
    "task",
    "base_branch",
    "branch_name",
)


def _build_command(raw: dict[str, Any]) -> AgentCommand:
    return AgentCommand(
        argv=tuple(raw["argv"]),
        cwd=raw.get("cwd"),
        returncode=int(raw.get("returncode", 0)),
        stdout_tail=str(raw.get("stdout_tail", "")),
        stderr_tail=str(raw.get("stderr_tail", "")),
        changed_paths_after=tuple(raw.get("changed_paths_after", ())),
    )


def _build_question(raw: dict[str, Any]) -> AgentQuestion:
    return AgentQuestion(
        text=str(raw["text"]),
        options=tuple(raw.get("options", ())),
    )


def _build_commit(raw: dict[str, Any]) -> AgentCommit:
    return AgentCommit(
        sha=str(raw["sha"]),
        subject=str(raw["subject"]),
        message=str(raw.get("message", "")),
        files_changed=tuple(raw.get("files_changed", ())),
    )


def _build_pr(raw: dict[str, Any] | None) -> AgentPR | None:
    if raw is None:
        return None
    return AgentPR(title=str(raw.get("title", "")), body=str(raw.get("body", "")))


def load_agent_run(path: Path) -> AgentRun:
    """Load a prerecorded :class:`AgentRun` from a YAML file."""
    raw = yaml.safe_load(path.read_text()) or {}
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        raise ValueError(f"AgentRun {path} missing keys: {missing}")

    return AgentRun(
        agent_id=str(raw["agent_id"]),
        scenario_id=str(raw["scenario_id"]),
        task=str(raw["task"]),
        base_branch=str(raw["base_branch"]),
        branch_name=str(raw["branch_name"]),
        commands=tuple(_build_command(c) for c in raw.get("commands", [])),
        questions=tuple(_build_question(q) for q in raw.get("questions", [])),
        commits=tuple(_build_commit(c) for c in raw.get("commits", [])),
        pr=_build_pr(raw.get("pr")),
        transcript_path=raw.get("transcript_path"),
    )
