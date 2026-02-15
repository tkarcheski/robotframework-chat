"""Tests for rfc.ci_metadata."""

import os
from unittest.mock import patch

from rfc.ci_metadata import collect_ci_metadata


class TestCollectCiMetadata:
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

    def test_ci_env_vars_included(self):
        with patch.dict(
            os.environ,
            {"CI_COMMIT_SHA": "abc123", "CI_COMMIT_REF_NAME": "main"},
            clear=True,
        ):
            result = collect_ci_metadata()
        assert result["Commit_SHA"] == "abc123"
        assert result["Branch"] == "main"

    def test_empty_values_filtered(self):
        with patch.dict(os.environ, {"CI_JOB_URL": ""}, clear=True):
            result = collect_ci_metadata()
        assert "Job_URL" not in result

    def test_gitlab_vars_collected(self):
        with patch.dict(
            os.environ,
            {
                "CI_PIPELINE_URL": "https://gitlab.com/pipeline/1",
                "CI_JOB_URL": "https://gitlab.com/job/1",
                "CI_RUNNER_ID": "42",
            },
            clear=True,
        ):
            result = collect_ci_metadata()
        assert result["Pipeline_URL"] == "https://gitlab.com/pipeline/1"
        assert result["Runner_ID"] == "42"
