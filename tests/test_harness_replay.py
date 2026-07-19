"""Tests for rfc.harness_replay — recorded-transcript replay run mode (RFC-010 S3, #261).

Two things are proven, both deterministically and with no agent CLI installed:

  * **Mode selection + corpus** — ``replay_requested()`` reads the same knobs the
    suite does (``HARNESS_MATRIX_REPLAY`` and the S2 ``RFC_RUN_MODE=replay``), the
    shipped recordings load, and ``build_replay_invoker`` answers the driver's
    subprocess calls from a recording.

  * **First-class run mode on HarnessKeywords** — with replay selected and no
    injected invoker, `Start` -> `Run` -> `End` drives a leg from the recorded
    corpus (no live agent, no tokens), produces an :class:`AgentRun` that passes
    the shared conformance verifiers, and stamps ``replay_of_recording_id`` on the
    ``agentic_harnesses`` spine so a green cell is never mistaken for a live pass.

The ``codex`` leg is used for the end-to-end case precisely because its CLI is
absent by default: a conformant replayed run with no binary installed is the
zero-token-CI property the slice exists for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfc.agent_verifiers import (
    assert_no_commit_while_tests_red,
    assert_run_did_positive_work,
)
from rfc.harness_adapters import ClaudeProcessResult
from rfc.harness_db import HarnessDatabase
from rfc.harness_keywords import HarnessKeywords
from rfc.harness_replay import (
    Recording,
    build_replay_invoker,
    has_recording,
    load_recording,
    recordings_dir,
    replay_requested,
)

_TOOLS = ("claude-code", "opencode", "codex")


@pytest.fixture(autouse=True)
def _clean_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No inherited run-mode env bleeds into a test."""
    monkeypatch.delenv("HARNESS_MATRIX_REPLAY", raising=False)
    monkeypatch.delenv("RFC_RUN_MODE", raising=False)
    monkeypatch.delenv("HARNESS_MATRIX_RECORDINGS_DIR", raising=False)


# ---------------------------------------------------------------------------
# Mode selection.
# ---------------------------------------------------------------------------


class TestReplayRequested:
    def test_off_by_default(self) -> None:
        assert replay_requested() is False

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_replay_env_truthy(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("HARNESS_MATRIX_REPLAY", value)
        assert replay_requested() is True

    @pytest.mark.parametrize("value", ["0", "", "off", "no"])
    def test_replay_env_falsy(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("HARNESS_MATRIX_REPLAY", value)
        assert replay_requested() is False

    def test_run_mode_replay_selects_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The S2 intent selects the S3 mode too, so one run mode drives both.
        monkeypatch.setenv("RFC_RUN_MODE", "replay")
        assert replay_requested() is True

    def test_run_mode_verify_does_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RFC_RUN_MODE", "verify")
        assert replay_requested() is False


# ---------------------------------------------------------------------------
# The shipped corpus.
# ---------------------------------------------------------------------------


class TestCorpus:
    @pytest.mark.parametrize("tool", _TOOLS)
    def test_every_harness_ships_a_recording(self, tool: str) -> None:
        assert has_recording(tool) is True
        rec = load_recording(tool)
        assert rec.tool == tool
        assert rec.recording_id
        assert rec.agent_transcript
        assert rec.git_log  # the commit fact the positive-work check reads

    def test_missing_recording_is_loud_not_silent(self, tmp_path: Path) -> None:
        # Honesty: a missing recording never silently falls through to a live
        # agent; it raises so the zero-token guarantee cannot be broken.
        monkeypatch_dir = tmp_path / "empty"
        monkeypatch_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="no recorded transcript"):
            load_recording("opencode", corpus_dir=monkeypatch_dir)

    def test_recordings_dir_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_MATRIX_RECORDINGS_DIR", "/tmp/custom-corpus")
        assert recordings_dir() == Path("/tmp/custom-corpus")


# ---------------------------------------------------------------------------
# The replay invoker answers the driver's subprocess calls from a recording.
# ---------------------------------------------------------------------------


class TestReplayInvoker:
    @staticmethod
    def _rec() -> Recording:
        return Recording(
            recording_id="rec-1",
            tool="opencode",
            agent_transcript="AGENT-TRANSCRIPT",
            git_log="LOG",
            git_show="SHOW",
            git_status_porcelain="STATUS",
        )

    def _call(self, argv: tuple[str, ...]) -> str:
        invoker = build_replay_invoker(self._rec())
        result = invoker(argv, Path("."), {}, 30)
        assert isinstance(result, ClaudeProcessResult)
        assert result.returncode == 0
        return result.stdout

    def test_git_log_returns_recorded_log(self) -> None:
        assert self._call(("git", "log", "--format=x", "origin/main..HEAD")) == "LOG"

    def test_git_show_returns_recorded_show(self) -> None:
        assert self._call(("git", "show", "--name-only", "--format=", "aaa")) == "SHOW"

    def test_status_returns_recorded_status(self) -> None:
        assert self._call(("git", "status", "--porcelain")) == "STATUS"

    def test_worktree_ops_are_empty(self) -> None:
        assert (
            self._call(("git", "worktree", "add", "-b", "b", "w", "origin/main")) == ""
        )

    def test_agent_argv_returns_transcript(self) -> None:
        assert self._call(("opencode", "run", "do a thing")) == "AGENT-TRANSCRIPT"


# ---------------------------------------------------------------------------
# First-class run mode on HarnessKeywords: replay drives a conformant leg with
# no agent CLI, and stamps replay provenance on the spine.
# ---------------------------------------------------------------------------


def _workspace(kw: HarnessKeywords, tmp_path: Path) -> dict:
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    return kw.create_harness_workspace(str(ws_dir))


class TestReplayRunMode:
    @pytest.mark.parametrize("tool", _TOOLS)
    def test_replay_leg_is_conformant_and_stamped(
        self, tmp_path: Path, tool: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_MATRIX_REPLAY", "1")
        # No injected invoker: the library self-wires the replay invoker from the
        # shipped corpus, so no real agent subprocess is spawned.
        kw = HarnessKeywords(repo_root=tmp_path / "repo")
        assert kw.replay_mode_requested() is True

        workspace = _workspace(kw, tmp_path)
        session = kw.start_harness_session(
            tool=tool,
            workspace=workspace["path"],
            database_url=workspace["database_url"],
        )
        run = kw.run_agent_task(
            task="Add a greet helper to src/rfc/example.py.", base_branch="main"
        )

        # The replayed run normalizes to the same conformant AgentRun the live
        # leg would: right harness, right branch namespace, real work, no commit
        # while tests red.
        assert run.agent_id == tool
        prefix = {"claude-code": "claude", "opencode": "opencode", "codex": "codex"}[
            tool
        ]
        assert run.branch_name.startswith(f"{prefix}/")
        assert_run_did_positive_work(run)
        assert_no_commit_while_tests_red(run)
        assert kw.get_agent_transcript() is run

        # Provenance is stamped on the spine (the honesty rule): the recording id
        # is on the agentic_harnesses row, retrievable via the keyword too.
        expected = load_recording(tool).recording_id
        assert kw.get_session_provenance() == expected
        row = HarnessDatabase(database_url=workspace["database_url"]).get_harness(
            session["session_id"]
        )
        assert row is not None
        assert row.replay_of_recording_id == expected

        kw.end_harness_session("success")

    def test_live_default_carries_no_replay_stamp(self, tmp_path: Path) -> None:
        # With replay unselected and an injected (stub) invoker, the session is a
        # live-shaped run: no replay provenance on the spine.
        def stub(argv, cwd, env, timeout):  # type: ignore[no-untyped-def]
            return ClaudeProcessResult(returncode=0, stdout="", stderr="")

        kw = HarnessKeywords(invoker=stub, repo_root=tmp_path / "repo")
        assert kw.replay_mode_requested() is False
        workspace = _workspace(kw, tmp_path)
        session = kw.start_harness_session(
            tool="opencode",
            workspace=workspace["path"],
            database_url=workspace["database_url"],
        )
        assert kw.get_session_provenance() == ""
        row = HarnessDatabase(database_url=workspace["database_url"]).get_harness(
            session["session_id"]
        )
        assert row is not None
        assert row.replay_of_recording_id == ""

    def test_injected_invoker_wins_over_replay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even under HARNESS_MATRIX_REPLAY=1, an explicitly injected invoker (the
        # pytest twin's seam) takes precedence and no --replay-of is stamped, so
        # the twin keeps full control of provenance.
        monkeypatch.setenv("HARNESS_MATRIX_REPLAY", "1")

        def stub(argv, cwd, env, timeout):  # type: ignore[no-untyped-def]
            return ClaudeProcessResult(returncode=0, stdout="", stderr="")

        kw = HarnessKeywords(invoker=stub, repo_root=tmp_path / "repo")
        workspace = _workspace(kw, tmp_path)
        kw.start_harness_session(
            tool="opencode",
            workspace=workspace["path"],
            database_url=workspace["database_url"],
        )
        assert kw.get_session_provenance() == ""

    def test_recording_available_matches_corpus(self) -> None:
        kw = HarnessKeywords()
        assert kw.recording_available("opencode") is True
        with pytest.raises(ValueError, match="unknown harness"):
            kw.recording_available("gemini")
