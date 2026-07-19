"""Recorded-transcript replay for the harness matrix (RFC-010 S3, #261).

The cross-harness conformance suite ``harness_matrix.robot`` is LIVE by default:
every leg spawns a real coding-agent subprocess in a real git worktree, so it
spends tokens and minutes. The deterministic *twin* of that suite already
exists in :mod:`tests.test_harness_keywords`, where an injected ``invoker``
replays a recorded transcript (Claude Code stream-json, opencode JSON, codex
JSONL) so a leg normalizes to an :class:`~rfc.agent_run.AgentRun` and runs the
``agent_verifiers`` assertions with no agent, no network, no tokens.

This module promotes that twin mechanism to a *selectable run mode on the live
suite*: with ``HARNESS_MATRIX_REPLAY=1`` (or the RFC-010 S2 ``RFC_RUN_MODE=replay``
intent) the conformance legs read a recorded transcript from the on-disk corpus
instead of spawning an agent. The corpus doubles as the record fixture: one
JSON recording per harness under ``robot/40__tier4/harness_matrix/recordings/``,
holding the native agent transcript plus the harness-agnostic git facts the
driver derives (log / show / status).

Honesty (RFC-010 §3): a replayed run stamps its provenance on the
``agentic_harnesses`` spine via ``replay_of_recording_id`` (see
:meth:`rfc.harness_keywords.HarnessKeywords.start_harness_session`), so a green
conformance cell is never mistaken for a fresh live pass — the same discipline
as ``cache_hit=True``. Replay never silently falls back to a live agent: a
missing recording is a loud :class:`FileNotFoundError`, not a token-spending
subprocess.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .harness_adapters import ClaudeProcessResult, ProcessInvoker

# Env knobs. ``HARNESS_MATRIX_REPLAY`` is the suite-local switch; the S2
# ``RFC_RUN_MODE=replay`` intent also selects replay so one run mode drives both
# the answer cache (S2) and the harness matrix (S3).
REPLAY_ENV = "HARNESS_MATRIX_REPLAY"
RECORDINGS_DIR_ENV = "HARNESS_MATRIX_RECORDINGS_DIR"
_RUN_MODE_ENV = "RFC_RUN_MODE"
_RUN_MODE_REPLAY = "replay"
_TRUTHY = {"1", "true", "yes", "on"}

# Default corpus lives beside the suite that consumes it (src/rfc/ -> src/ ->
# core/ -> robot/...), so the recorded transcripts double as the record fixture.
_DEFAULT_RECORDINGS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "robot"
    / "40__tier4"
    / "harness_matrix"
    / "recordings"
)


def replay_requested() -> bool:
    """Whether this run should replay recorded transcripts rather than go live.

    True when ``HARNESS_MATRIX_REPLAY`` is truthy or ``RFC_RUN_MODE=replay`` (the
    S2 intent). Mirrors :func:`rfc.llm_client._cache_enabled_for_run_mode`'s
    reading of the same ``RFC_RUN_MODE`` gate so one selection drives both.
    """
    if os.getenv(REPLAY_ENV, "").strip().lower() in _TRUTHY:
        return True
    return os.getenv(_RUN_MODE_ENV, "").strip().lower() == _RUN_MODE_REPLAY


def recordings_dir() -> Path:
    """The recorded-transcript corpus directory (``HARNESS_MATRIX_RECORDINGS_DIR``
    overrides the default beside the suite)."""
    override = os.getenv(RECORDINGS_DIR_ENV, "").strip()
    return Path(override) if override else _DEFAULT_RECORDINGS_DIR


@dataclass(frozen=True)
class Recording:
    """One recorded harness run: the native transcript plus git facts.

    ``agent_transcript`` is the harness's native CLI transcript (what the adapter
    parser consumes); the git fields are the harness-agnostic replies the driver
    derives itself (``git log`` / ``git show`` / ``git status --porcelain``).
    """

    recording_id: str
    tool: str
    agent_transcript: str
    git_log: str
    git_show: str
    git_status_porcelain: str


def recording_path(tool: str, corpus_dir: Path | None = None) -> Path:
    """Path to ``tool``'s recording JSON in the corpus."""
    return (corpus_dir or recordings_dir()) / f"{tool}.json"


def has_recording(tool: str, corpus_dir: Path | None = None) -> bool:
    """Whether a recorded transcript exists for ``tool`` (probe-only)."""
    return recording_path(tool, corpus_dir).is_file()


def load_recording(tool: str, corpus_dir: Path | None = None) -> Recording:
    """Load ``tool``'s recording, raising loudly if the corpus lacks it.

    A missing recording is a hard :class:`FileNotFoundError`, never a silent
    fall-through to a live agent — the honesty rule that keeps the zero-token
    guarantee (RFC-010 §3).
    """
    path = recording_path(tool, corpus_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"no recorded transcript for harness {tool!r} at {path}; "
            "replay refuses to silently spawn a live agent"
        )
    raw = json.loads(path.read_text())
    git = raw.get("git", {})
    return Recording(
        recording_id=str(raw["recording_id"]),
        tool=str(raw.get("tool", tool)),
        agent_transcript=str(raw["agent_transcript"]),
        git_log=str(git.get("log", "")),
        git_show=str(git.get("show", "")),
        git_status_porcelain=str(git.get("status_porcelain", "")),
    )


def build_replay_invoker(recording: Recording) -> ProcessInvoker:
    """A :data:`ProcessInvoker` that replays ``recording`` in place of subprocesses.

    :class:`~rfc.live_agent_runner.LiveClaudeCodeRunner` routes every subprocess
    through its invoker: the git worktree create/remove, the agent invocation,
    and the git bookkeeping reads (log / show / status). This shim answers each
    from the recording — the git facts from the recorded replies, everything
    non-git (the agent argv) from the recorded transcript — so no real agent,
    git, network, or token is touched. It mirrors the ``StubInvoker`` /
    ``_shared_git_canned`` seam the deterministic twin already relies on.
    """

    def _ok(stdout: str) -> ClaudeProcessResult:
        return ClaudeProcessResult(returncode=0, stdout=stdout, stderr="")

    def invoker(
        argv: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> ClaudeProcessResult:
        joined = " ".join(argv)
        if "git log" in joined:
            return _ok(recording.git_log)
        if "git show" in joined:
            return _ok(recording.git_show)
        if "status --porcelain" in joined:
            return _ok(recording.git_status_porcelain)
        if "worktree" in joined:
            # worktree add / remove: harness-agnostic bookkeeping, no output.
            return _ok("")
        # Anything else is the agent invocation itself.
        return _ok(recording.agent_transcript)

    return invoker
