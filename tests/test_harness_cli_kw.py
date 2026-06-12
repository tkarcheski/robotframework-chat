"""Tests for rfc.harness_cli_kw — Robot keyword library for the harness CLI.

The library drives the real ``rfc harness`` CLI as subprocesses inside a
throwaway git repo + sqlite database, so the Robot suite exercises the
sidecar/DB behaviour end-to-end and cross-process.
"""

import json

import pytest

from rfc.harness_cli_kw import HarnessCliRunner


@pytest.fixture()
def runner():
    return HarnessCliRunner()


@pytest.fixture()
def workspace(runner, tmp_path):
    return runner.create_harness_workspace(str(tmp_path))


class TestCreateHarnessWorkspace:
    def test_creates_git_repo_with_sqlite_url(self, runner, tmp_path):
        ws = runner.create_harness_workspace(str(tmp_path))
        assert (tmp_path / ".git").is_dir()
        assert ws["path"] == str(tmp_path)
        assert ws["database_url"].startswith("sqlite:///")
        assert ws["sidecar"].endswith("rfc-harness-session.json")


class TestRunHarnessCommand:
    def test_start_returns_rc_zero_and_writes_sidecar(self, runner, workspace):
        result = runner.run_harness_command(workspace, "start", "--tool", "claude-code")
        assert result["rc"] == 0
        assert "started session" in result["stdout"]
        sidecar = json.loads(open(workspace["sidecar"]).read())
        assert sidecar["tool_name"] == "claude-code"

    def test_runs_in_separate_process_sharing_sidecar(self, runner, workspace):
        runner.run_harness_command(workspace, "start", "--tool", "claude-code")
        status = runner.run_harness_command(workspace, "status")
        assert status["rc"] == 0
        assert "active session" in status["stdout"]

    def test_end_without_session_fails_with_message(self, runner, workspace):
        result = runner.run_harness_command(workspace, "end")
        assert result["rc"] == 1
        assert "no active session" in result["stderr"]


class TestSidecarKeywords:
    def test_session_id_matches_sidecar(self, runner, workspace):
        runner.run_harness_command(workspace, "start", "--tool", "codex")
        session_id = runner.get_sidecar_session_id(workspace)
        on_disk = json.loads(open(workspace["sidecar"]).read())["session_id"]
        assert session_id == on_disk

    def test_session_id_fails_without_sidecar(self, runner, workspace):
        with pytest.raises(AssertionError, match="no sidecar"):
            runner.get_sidecar_session_id(workspace)

    def test_sidecar_should_not_exist(self, runner, workspace):
        runner.sidecar_should_not_exist(workspace)
        runner.run_harness_command(workspace, "start", "--tool", "codex")
        with pytest.raises(AssertionError, match="sidecar still present"):
            runner.sidecar_should_not_exist(workspace)


class TestGetHarnessRow:
    def test_returns_row_as_dict(self, runner, workspace):
        runner.run_harness_command(workspace, "start", "--tool", "claude-code")
        session_id = runner.get_sidecar_session_id(workspace)
        row = runner.get_harness_row(workspace, session_id)
        assert row["session_id"] == session_id
        assert row["tool_name"] == "claude-code"
        assert row["started_at"]
        assert row["ended_at"] == ""

    def test_fails_for_unknown_session(self, runner, workspace):
        with pytest.raises(AssertionError, match="no agentic_harnesses row"):
            runner.get_harness_row(workspace, "does-not-exist")

    def test_end_sets_ended_at_and_outcome(self, runner, workspace):
        runner.run_harness_command(workspace, "start", "--tool", "claude-code")
        session_id = runner.get_sidecar_session_id(workspace)
        runner.run_harness_command(workspace, "end", "--outcome", "success")
        row = runner.get_harness_row(workspace, session_id)
        assert row["ended_at"]
        assert row["outcome"] == "success"


class TestMakefileSessionId:
    def test_returns_sidecar_id_while_active(self, runner, workspace):
        runner.run_harness_command(workspace, "start", "--tool", "claude-code")
        session_id = runner.get_sidecar_session_id(workspace)
        assert runner.get_makefile_session_id(workspace) == session_id

    def test_returns_fresh_uuid_after_end(self, runner, workspace):
        runner.run_harness_command(workspace, "start", "--tool", "claude-code")
        active = runner.get_sidecar_session_id(workspace)
        runner.run_harness_command(workspace, "end")
        first = runner.get_makefile_session_id(workspace)
        second = runner.get_makefile_session_id(workspace)
        assert first != active
        assert first != second  # fresh UUID per invocation
