"""Tests for rfc.harness_keywords — the public HarnessKeywords RF library (#173).

The library runs one coding-agent task inside an ``rfc harness`` session bracket
and normalizes the CLI transcript into an :class:`AgentRun`. Two things are
proven here, both deterministically:

  * **Session bracketing** — `Start Harness Session` writes a real
    ``agentic_harnesses`` row (via a subprocess ``rfc harness start`` in a
    throwaway git repo) and `End Harness Session` closes it.
  * **Cross-harness conformance** — the SAME logical fixture run, recorded in
    each harness's native transcript format (Claude Code stream-json, opencode
    JSON, codex JSONL), normalizes to an :class:`AgentRun` that passes the SAME
    :mod:`rfc.agent_verifiers` assertions. This is the deterministic twin of the
    live ``harness_matrix`` robot suite.

The *agent* invocation is stubbed (an injected invoker replays a recorded
transcript), so no real agent runs and there is no network or token spend. The
harness-session subprocess is real and hermetic (its own sqlite file).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from rfc.agent_contract import AgentContract
from rfc.agent_run import AgentRun
from rfc.agent_verifiers import (
    assert_all_commits_match_convention,
    assert_branch_matches_contract,
    assert_commands_appear_in_order,
    assert_no_commit_while_tests_red,
)
from rfc.harness_adapters import (
    ClaudeProcessResult,
    CodexAdapter,
    OpenCodeAdapter,
)
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticHarness
from rfc.harness_keywords import HarnessKeywords

# ---------------------------------------------------------------------------
# Stub invoker (matches the shape used by the live-runner + adapter tests).
# ---------------------------------------------------------------------------


@dataclass
class StubInvoker:
    """Return canned ClaudeProcessResults per command-substring match."""

    canned: dict[str, ClaudeProcessResult] = field(default_factory=dict)
    default: ClaudeProcessResult = field(
        default_factory=lambda: ClaudeProcessResult(returncode=0, stdout="", stderr="")
    )
    calls: list[tuple[tuple[str, ...], Path, dict[str, str], int]] = field(
        default_factory=list
    )

    def __call__(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> ClaudeProcessResult:
        self.calls.append((argv, cwd, dict(env), timeout))
        joined = " ".join(argv)
        for needle, result in self.canned.items():
            if needle in joined:
                return result
        return self.default


# ---------------------------------------------------------------------------
# The SAME logical fixture run, one recording per harness transcript format:
#   1. `uv run pytest`                       -> green
#   2. `git commit -m "feat: add greet ..."` -> committed
# ---------------------------------------------------------------------------

_PYTEST_CMD = "uv run pytest"
_COMMIT_CMD = 'git commit -m "feat: add greet helper"'
_COMMIT_SUBJECT = "feat: add greet helper"


def _jsonl(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _claude_transcript() -> str:
    def bash(tool_id: str, command: str) -> dict[str, Any]:
        return {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "Bash",
                        "input": {"command": command},
                    }
                ]
            },
        }

    def result(tool_id: str, text: str) -> dict[str, Any]:
        return {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": [{"type": "text", "text": text}],
                        "is_error": False,
                    }
                ]
            },
        }

    return _jsonl(
        [
            bash("t1", _PYTEST_CMD),
            result("t1", "5 passed in 0.2s"),
            bash("t2", _COMMIT_CMD),
            result("t2", "1 file changed"),
        ]
    )


def _opencode_transcript() -> str:
    def bash(call_id: str, command: str, output: str) -> dict[str, Any]:
        return {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "bash",
                "callID": call_id,
                "state": {
                    "status": "completed",
                    "input": {"command": command},
                    "output": output,
                },
            },
        }

    return _jsonl(
        [
            bash("c1", _PYTEST_CMD, "5 passed in 0.2s"),
            bash("c2", _COMMIT_CMD, "1 file changed"),
        ]
    )


def _codex_transcript() -> str:
    def begin(call_id: str, command: str) -> dict[str, Any]:
        return {
            "msg": {
                "type": "exec_command_begin",
                "call_id": call_id,
                "command": ["bash", "-lc", command],
            }
        }

    def end(call_id: str, stdout: str) -> dict[str, Any]:
        return {
            "msg": {
                "type": "exec_command_end",
                "call_id": call_id,
                "stdout": stdout,
                "stderr": "",
                "exit_code": 0,
            }
        }

    return _jsonl(
        [
            begin("c1", _PYTEST_CMD),
            end("c1", "5 passed in 0.2s"),
            begin("c2", _COMMIT_CMD),
            end("c2", "1 file changed"),
        ]
    )


# tool -> (agent-argv needle, branch prefix, transcript-builder)
_HARNESSES: dict[str, tuple[str, str, Any]] = {
    "claude-code": ("claude -p", "claude", _claude_transcript),
    "opencode": ("opencode run", "opencode", _opencode_transcript),
    "codex": ("codex exec", "codex", _codex_transcript),
}


def _shared_git_canned(
    agent_needle: str, transcript: str
) -> dict[str, ClaudeProcessResult]:
    """Canned invoker replies: the agent transcript plus the driver's git reads.

    The git replies (log/show/status) are identical for every harness — commits
    and changed paths are harness-agnostic git facts the driver derives itself.
    """
    return {
        agent_needle: ClaudeProcessResult(returncode=0, stdout=transcript, stderr=""),
        "git log": ClaudeProcessResult(
            returncode=0,
            stdout=f"aaa111\x1f{_COMMIT_SUBJECT}\x1fbody\x1e\n",
            stderr="",
        ),
        "git show": ClaudeProcessResult(
            returncode=0, stdout="src/rfc/example.py\n", stderr=""
        ),
        "status --porcelain": ClaudeProcessResult(
            returncode=0, stdout=" M src/rfc/example.py\n", stderr=""
        ),
    }


def _contract(agent_id: str, branch_prefix: str) -> AgentContract:
    return AgentContract(
        agent_id=agent_id,
        base_branch="main",
        branch_regex=rf"^{branch_prefix}/[a-z0-9-]+-[0-9a-f]{{5}}$",
        startup_checks=(),
        pr_template_path="",
        pr_required_sections=(),
        commit_types=("feat", "fix", "test", "docs", "refactor", "chore"),
        commit_subject_regex=r"^(feat|fix|test|docs|refactor|chore)(\(.+\))?: .+",
        min_clarifying_questions=0,
        max_clarifying_questions=5,
    )


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def _make_keywords(tmp_path: Path, invoker: StubInvoker) -> HarnessKeywords:
    return HarnessKeywords(invoker=invoker, repo_root=tmp_path / "repo")


def _bracketed_run(
    tmp_path: Path, tool: str
) -> tuple[HarnessKeywords, dict, AgentRun, str, str]:
    """Drive Create -> Start -> Run -> End for ``tool`` with a stub agent.

    Returns ``(kw, workspace, run, session_id, branch_prefix)``.
    """
    agent_needle, branch_prefix, builder = _HARNESSES[tool]
    invoker = StubInvoker(canned=_shared_git_canned(agent_needle, builder()))
    kw = _make_keywords(tmp_path, invoker)
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    workspace = kw.create_harness_workspace(str(ws_dir))
    session = kw.start_harness_session(
        tool=tool, workspace=workspace["path"], database_url=workspace["database_url"]
    )
    run = kw.run_agent_task(
        task="Add a greet helper to src/rfc/example.py.", base_branch="main"
    )
    return kw, workspace, run, session["session_id"], branch_prefix


# ---------------------------------------------------------------------------
# Probe + adapter selection (no subprocess).
# ---------------------------------------------------------------------------


class TestHarnessIsAvailable:
    def test_probe_true_for_present_stand_in(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ClaudeCodeAdapter.probe() shells out to `claude --version`; stub the
        # binary check so the test never depends on a real install.
        import rfc.harness_adapters as ha

        monkeypatch.setattr(ha, "_probe_binary", lambda *a, **k: True)
        assert HarnessKeywords().harness_is_available("codex") is True

    def test_probe_false_for_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import rfc.harness_adapters as ha

        monkeypatch.setattr(ha, "_probe_binary", lambda *a, **k: False)
        assert HarnessKeywords().harness_is_available("claude-code") is False

    def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown harness"):
            HarnessKeywords().harness_is_available("gemini")


class TestAdapterSelection:
    def test_opencode_gets_model_and_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "opencode.json"
        cfg.write_text("{}")
        kw = HarnessKeywords(opencode_config=cfg)
        adapter = kw._build_adapter("opencode", "ollama/qwen3-coder:30b")
        assert isinstance(adapter, OpenCodeAdapter)
        assert adapter.model == "ollama/qwen3-coder:30b"
        assert adapter.env_overrides() == {"OPENCODE_CONFIG": str(cfg)}

    def test_codex_selects_codex_adapter(self) -> None:
        assert isinstance(HarnessKeywords()._build_adapter("codex", ""), CodexAdapter)

    def test_opencode_missing_config_is_dropped(self, tmp_path: Path) -> None:
        kw = HarnessKeywords(opencode_config=tmp_path / "does-not-exist.json")
        adapter = kw._build_adapter("opencode", "")
        assert isinstance(adapter, OpenCodeAdapter)
        assert adapter.env_overrides() == {}


# ---------------------------------------------------------------------------
# Session lifecycle: the agentic_harnesses row is written and closed.
# ---------------------------------------------------------------------------


class TestSessionBracket:
    @pytest.mark.parametrize("tool", list(_HARNESSES))
    def test_start_writes_open_harness_row(self, tmp_path: Path, tool: str) -> None:
        kw, workspace, _run, session_id, _prefix = _bracketed_run(tmp_path, tool)
        db = HarnessDatabase(database_url=workspace["database_url"])
        row = db.get_harness(session_id)
        assert row is not None
        assert row.tool_name == tool
        assert row.ended_at == ""  # still open until End

    @pytest.mark.parametrize("tool", list(_HARNESSES))
    def test_end_closes_harness_row(self, tmp_path: Path, tool: str) -> None:
        kw, workspace, _run, session_id, _prefix = _bracketed_run(tmp_path, tool)
        kw.end_harness_session("success")
        db = HarnessDatabase(database_url=workspace["database_url"])
        row = db.get_harness(session_id)
        assert row is not None
        assert row.ended_at != ""
        assert row.outcome == "success"

    def test_start_requires_database(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        kw = HarnessKeywords()
        workspace = kw.create_harness_workspace(str(ws_dir))
        with pytest.raises(ValueError, match="no database configured"):
            kw.start_harness_session(tool="opencode", workspace=workspace["path"])

    def test_start_rejects_unknown_tool(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown harness"):
            HarnessKeywords().start_harness_session(
                tool="gemini", workspace=str(tmp_path), database_url="sqlite:///x.db"
            )

    def test_end_rejects_bad_outcome(self, tmp_path: Path) -> None:
        _kw, _ws, _run, _sid, _prefix = _bracketed_run(tmp_path, "opencode")
        with pytest.raises(ValueError, match="invalid outcome"):
            _kw.end_harness_session("done")


# ---------------------------------------------------------------------------
# Transcript capture + error guards.
# ---------------------------------------------------------------------------


class TestTranscript:
    def test_run_dispatches_through_selected_adapter(self, tmp_path: Path) -> None:
        _kw, _ws, run, _sid, _prefix = _bracketed_run(tmp_path, "opencode")
        # The opencode agent argv must have been invoked (adapter dispatch).
        assert any(
            "opencode run" in " ".join(c[0])
            for c in _kw._invoker.calls  # type: ignore[union-attr]
        )
        assert run.agent_id == "opencode"

    def test_get_agent_transcript_returns_last_run(self, tmp_path: Path) -> None:
        kw, _ws, run, _sid, _prefix = _bracketed_run(tmp_path, "claude-code")
        assert kw.get_agent_transcript() is run

    def test_get_transcript_before_run_raises(self) -> None:
        with pytest.raises(AssertionError, match="no agent run"):
            HarnessKeywords().get_agent_transcript()

    def test_run_without_session_raises(self) -> None:
        with pytest.raises(AssertionError, match="no active harness session"):
            HarnessKeywords().run_agent_task("do a thing")


# ---------------------------------------------------------------------------
# Cross-harness conformance: identical verifier outcomes for the same fixture.
# ---------------------------------------------------------------------------


class TestCrossHarnessConformance:
    @pytest.mark.parametrize("tool", list(_HARNESSES))
    def test_same_fixture_passes_same_verifiers(
        self, tmp_path: Path, tool: str
    ) -> None:
        _kw, _ws, run, _sid, branch_prefix = _bracketed_run(tmp_path, tool)
        contract = _contract(run.agent_id, branch_prefix)

        # Every harness normalizes to the same contract outcome.
        assert_branch_matches_contract(run, contract)
        assert_commands_appear_in_order(run, (_PYTEST_CMD, "git commit"))
        assert_no_commit_while_tests_red(run)
        assert_all_commits_match_convention(run, contract)

    def test_all_harnesses_yield_equivalent_command_streams(
        self, tmp_path: Path
    ) -> None:
        streams: dict[str, list[str]] = {}
        for tool in _HARNESSES:
            # Fresh tmp per tool so the workspaces do not collide.
            sub = tmp_path / tool.replace("-", "_")
            sub.mkdir()
            _kw, _ws, run, _sid, _prefix = _bracketed_run(sub, tool)
            streams[tool] = [
                sub for cmd in run.commands for sub in cmd.shell_subcommands()
            ]
        # The recorded fixtures differ only in transcript FORMAT; the normalized
        # command streams must be identical across harnesses.
        values = list(streams.values())
        assert all(stream == values[0] for stream in values), streams


# ---------------------------------------------------------------------------
# Failure envelope: the session bracket must stay closeable when a run dies.
#
# This is the RSI-critical property (#169/#164 read the agentic_harnesses
# spine): a crashed or hung agent run must NOT leave a dangling open session
# row, and the two-sided guards (start twice / end twice / end-without-start)
# must fail loudly rather than silently double-write the DB.
# ---------------------------------------------------------------------------

_AGENT_NEEDLES = tuple(needle for needle, _p, _b in _HARNESSES.values())


class _RaisingAgentInvoker(StubInvoker):
    """Succeed on git bookkeeping; explode on the agent argv (a crashed run)."""

    def __call__(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> ClaudeProcessResult:
        joined = " ".join(argv)
        if any(needle in joined for needle in _AGENT_NEEDLES):
            raise RuntimeError("agent process exploded mid-run")
        return super().__call__(argv, cwd, env, timeout)


class _TimeoutAgentInvoker(StubInvoker):
    """Succeed on git bookkeeping; time out on the agent argv (a hung run)."""

    def __call__(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> ClaudeProcessResult:
        import subprocess

        joined = " ".join(argv)
        if any(needle in joined for needle in _AGENT_NEEDLES):
            raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout)
        return super().__call__(argv, cwd, env, timeout)


def _started(
    tmp_path: Path, tool: str, invoker: StubInvoker
) -> tuple[HarnessKeywords, dict, str]:
    """Create a workspace and open a session (no run yet)."""
    kw = _make_keywords(tmp_path, invoker)
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    workspace = kw.create_harness_workspace(str(ws_dir))
    session = kw.start_harness_session(
        tool=tool, workspace=workspace["path"], database_url=workspace["database_url"]
    )
    return kw, workspace, session["session_id"]


def _row(database_url: str, session_id: str) -> AgenticHarness:
    """Fetch the harness row, asserting it exists (keeps mypy + intent honest)."""
    row = HarnessDatabase(database_url=database_url).get_harness(session_id)
    assert row is not None
    return row


class TestFailureEnvelope:
    def test_crashed_run_leaves_session_closeable_as_failed(
        self, tmp_path: Path
    ) -> None:
        """Agent dies mid-run -> the row is still openable/closeable, not orphaned."""
        agent_needle, _prefix, builder = _HARNESSES["opencode"]
        inv = _RaisingAgentInvoker(canned=_shared_git_canned(agent_needle, builder()))
        kw, workspace, sid = _started(tmp_path, "opencode", inv)

        with pytest.raises(RuntimeError, match="exploded"):
            kw.run_agent_task(task="do a thing", base_branch="main")

        # Still OPEN right after the crash (the bracket has not been closed yet).
        assert _row(workspace["database_url"], sid).ended_at == ""

        # The caller's teardown can always close it -> no dangling open session.
        kw.end_harness_session("failed")
        closed = _row(workspace["database_url"], sid)
        assert closed.ended_at != ""
        assert closed.outcome == "failed"

    def test_hung_run_times_out_and_stays_closeable(self, tmp_path: Path) -> None:
        """A hung agent surfaces TimeoutExpired; the session is still closeable."""
        import subprocess

        agent_needle, _prefix, builder = _HARNESSES["opencode"]
        inv = _TimeoutAgentInvoker(canned=_shared_git_canned(agent_needle, builder()))
        kw, workspace, sid = _started(tmp_path, "opencode", inv)

        with pytest.raises(subprocess.TimeoutExpired):
            kw.run_agent_task(task="do a thing", base_branch="main")

        kw.end_harness_session("failed")
        assert _row(workspace["database_url"], sid).ended_at != ""

    def test_double_start_is_rejected_without_clobbering_first(
        self, tmp_path: Path
    ) -> None:
        """A second Start over a live sidecar fails loudly and keeps the first."""
        agent_needle, _prefix, builder = _HARNESSES["opencode"]
        inv = StubInvoker(canned=_shared_git_canned(agent_needle, builder()))
        kw, workspace, sid1 = _started(tmp_path, "opencode", inv)

        with pytest.raises(AssertionError, match="harness start"):
            kw.start_harness_session(
                tool="opencode",
                workspace=workspace["path"],
                database_url=workspace["database_url"],
            )
        # The first session is untouched and still the active one.
        assert kw._session is not None
        assert kw._session["session_id"] == sid1
        assert _row(workspace["database_url"], sid1).ended_at == ""

    def test_double_end_raises_rather_than_double_closing(self, tmp_path: Path) -> None:
        _kw, _ws, _run, _sid, _prefix = _bracketed_run(tmp_path, "opencode")
        _kw.end_harness_session("success")
        with pytest.raises(AssertionError, match="no active harness session"):
            _kw.end_harness_session("success")

    def test_end_without_start_raises(self) -> None:
        with pytest.raises(AssertionError, match="no active harness session"):
            HarnessKeywords().end_harness_session("success")
