"""Tests for rfc.git_metadata."""

import os
from unittest.mock import patch

from rfc.git_metadata import collect_ci_metadata, detect_ci_platform


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
    def test_always_has_timestamp(self):
        with patch.dict(os.environ, {}, clear=True):
            result = collect_ci_metadata()
        assert "Timestamp" in result
        assert result["Timestamp"].endswith("Z")

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

    def test_no_ci_platform(self):
        with patch.dict(os.environ, {}, clear=True):
            result = collect_ci_metadata()
        assert result.get("CI") == "false"
        assert "CI_Platform" not in result
