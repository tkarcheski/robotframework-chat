"""Tests for rfc.git_metadata."""

import os
from unittest.mock import MagicMock, patch

from rfc.git_metadata import (
    _collect_local_metadata,
    _git_command,
    collect_ci_metadata,
    detect_ci_platform,
)


class TestDetectCiPlatform:
    def test_detects_github(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            assert detect_ci_platform() == "github"

    def test_detects_gitlab(self):
        with patch.dict(os.environ, {"GITLAB_CI": "true"}, clear=True):
            assert detect_ci_platform() == "gitlab"

    def test_returns_none_outside_ci(self):
        with patch.dict(os.environ, {}, clear=True):
            assert detect_ci_platform() is None


class TestCollectGitMetadata:
    def test_always_has_valid_timestamp(self):
        with patch.dict(os.environ, {}, clear=True):
            result = collect_ci_metadata()
        assert "Timestamp" in result
        assert result["Timestamp"].endswith("Z")
        assert "+00:00" not in result["Timestamp"]

    def test_always_has_default_model(self):
        with patch.dict(os.environ, {}, clear=True):
            result = collect_ci_metadata()
        assert "Default_Model" in result

    def test_always_has_ollama_endpoint(self):
        with patch.dict(os.environ, {}, clear=True):
            result = collect_ci_metadata()
        assert "Ollama_Endpoint" in result

    def test_gitlab_env_vars_included(self):
        with patch.dict(
            os.environ,
            {
                "GITLAB_CI": "true",
                "CI_COMMIT_SHA": "abc123",
                "CI_COMMIT_REF_NAME": "main",
            },
            clear=True,
        ):
            result = collect_ci_metadata()
        assert result["Commit_SHA"] == "abc123"
        assert result["Branch"] == "main"
        assert result["CI_Platform"] == "gitlab"

    def test_github_env_vars_included(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_SHA": "def456789abcdef0",
                "GITHUB_REF_NAME": "feature-branch",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "org/repo",
                "GITHUB_RUN_ID": "12345",
            },
            clear=True,
        ):
            result = collect_ci_metadata()
        assert result["Commit_SHA"] == "def456789abcdef0"
        assert result["Commit_Short_SHA"] == "def45678"
        assert result["Branch"] == "feature-branch"
        assert result["CI_Platform"] == "github"
        assert result["Project_URL"] == "https://github.com/org/repo"
        assert "12345" in result["Pipeline_URL"]

    def test_empty_values_filtered(self):
        with patch.dict(
            os.environ,
            {"GITLAB_CI": "true", "CI_JOB_URL": ""},
            clear=True,
        ):
            result = collect_ci_metadata()
        assert "Job_URL" not in result

    def test_gitlab_vars_collected(self):
        with patch.dict(
            os.environ,
            {
                "GITLAB_CI": "true",
                "CI_PIPELINE_URL": "https://gitlab.com/pipeline/1",
                "CI_JOB_URL": "https://gitlab.com/job/1",
                "CI_RUNNER_ID": "42",
            },
            clear=True,
        ):
            result = collect_ci_metadata()
        assert result["Pipeline_URL"] == "https://gitlab.com/pipeline/1"
        assert result["Runner_ID"] == "42"

    @patch("rfc.git_metadata.subprocess.run")
    def test_no_ci_platform_uses_local_metadata(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="main\n"),
            MagicMock(returncode=0, stdout="abc123def456\n"),
        ]
        with patch.dict(os.environ, {}, clear=True):
            result = collect_ci_metadata()
        assert result.get("CI") == "false"
        assert result.get("CI_Platform") == "local"
        assert result.get("Branch") == "main"
        assert result.get("Commit_SHA") == "abc123def456"


class TestCollectLocalMetadata:
    @patch("rfc.git_metadata.subprocess.run")
    def test_has_branch(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="feature-branch\n"),
            MagicMock(returncode=0, stdout="abc123def456\n"),
        ]
        result = _collect_local_metadata()
        assert result["Branch"] == "feature-branch"

    @patch("rfc.git_metadata.subprocess.run")
    def test_has_commit_sha(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="main\n"),
            MagicMock(returncode=0, stdout="abc123def456789000\n"),
        ]
        result = _collect_local_metadata()
        assert result["Commit_SHA"] == "abc123def456789000"
        assert result["Commit_Short_SHA"] == "abc123de"

    @patch("rfc.git_metadata.subprocess.run")
    def test_ci_platform_is_local(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="main\n"),
            MagicMock(returncode=0, stdout="abc123\n"),
        ]
        result = _collect_local_metadata()
        assert result["CI"] == "false"
        assert result["CI_Platform"] == "local"

    @patch("rfc.git_metadata.subprocess.run")
    def test_git_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        result = _collect_local_metadata()
        assert result["CI"] == "false"
        assert result["CI_Platform"] == "local"
        assert result["Branch"] == ""
        assert result["Commit_SHA"] == ""

    @patch("rfc.git_metadata.subprocess.run")
    def test_not_a_git_repo(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        result = _collect_local_metadata()
        assert result["Branch"] == ""
        assert result["Commit_SHA"] == ""

    @patch("rfc.git_metadata.subprocess.run")
    def test_strips_whitespace(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  main  \n"),
            MagicMock(returncode=0, stdout="  abc123  \n"),
        ]
        result = _collect_local_metadata()
        assert result["Branch"] == "main"
        assert result["Commit_SHA"] == "abc123"

    @patch("rfc.git_metadata.subprocess.run")
    def test_detached_head(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="HEAD\n"),
            MagicMock(returncode=0, stdout="abc123def456\n"),
        ]
        result = _collect_local_metadata()
        assert result["Branch"] == "HEAD"


class TestGitCommand:
    @patch("rfc.git_metadata.subprocess.run")
    def test_returns_stdout_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        assert _git_command("rev-parse", "--abbrev-ref", "HEAD") == "main"

    @patch("rfc.git_metadata.subprocess.run")
    def test_returns_empty_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        assert _git_command("rev-parse", "HEAD") == ""

    @patch("rfc.git_metadata.subprocess.run")
    def test_returns_empty_on_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert _git_command("rev-parse", "HEAD") == ""

    @patch("rfc.git_metadata.subprocess.run")
    def test_returns_empty_on_timeout(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
        assert _git_command("rev-parse", "HEAD") == ""

    @patch("rfc.git_metadata.subprocess.run")
    def test_returns_empty_on_os_error(self, mock_run):
        mock_run.side_effect = OSError("permission denied")
        assert _git_command("rev-parse", "HEAD") == ""
