"""Tests for CI pipeline results sync to database."""

import argparse
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.sync_ci_results import (
    GitLabArtifactFetcher,
    cmd_fetch_artifact,
    cmd_list_jobs,
    cmd_list_pipelines,
    cmd_status,
    cmd_sync,
    cmd_verify,
    sync_ci_results,
    verify_sync,
)


# ---------------------------------------------------------------------------
# GitLabArtifactFetcher: init / config resolution
# ---------------------------------------------------------------------------


class TestGitLabArtifactFetcherInit:
    """Tests for GitLabArtifactFetcher construction and config resolution."""

    def test_init_from_explicit_params(self):
        """Constructor accepts api_url, project_id, token directly."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="tok"
        )
        assert fetcher._api_url == "https://gl.test"
        assert fetcher._project_id == "42"
        assert fetcher._token == "tok"

    @patch.dict(
        os.environ,
        {
            "GITLAB_API_URL": "https://gl.env",
            "GITLAB_PROJECT_ID": "99",
            "GITLAB_TOKEN": "envtok",
        },
        clear=True,
    )
    def test_init_from_env_vars(self):
        """Reads GITLAB_API_URL, GITLAB_PROJECT_ID, GITLAB_TOKEN from env."""
        fetcher = GitLabArtifactFetcher()
        assert fetcher._api_url == "https://gl.env"
        assert fetcher._project_id == "99"
        assert fetcher._token == "envtok"

    @patch.dict(
        os.environ,
        {
            "CI_API_V4_URL": "https://ci.gl/api/v4",
            "CI_PROJECT_ID": "7",
            "GITLAB_API_URL": "https://other.gl",
            "GITLAB_PROJECT_ID": "1",
        },
        clear=True,
    )
    def test_init_ci_env_vars_take_priority(self):
        """CI_API_V4_URL / CI_PROJECT_ID take priority over GITLAB_* vars."""
        fetcher = GitLabArtifactFetcher()
        assert fetcher._api_url == "https://ci.gl"
        assert fetcher._project_id == "7"

    @patch.dict(os.environ, {}, clear=True)
    def test_init_raises_without_config(self):
        """Raises ValueError when no GitLab config is available."""
        with pytest.raises(ValueError, match="GitLab API URL"):
            GitLabArtifactFetcher()

    def test_headers_include_token(self):
        """PRIVATE-TOKEN header is set when token is provided."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="1", token="tok123"
        )
        headers = fetcher._headers()
        assert headers["PRIVATE-TOKEN"] == "tok123"

    def test_headers_without_token(self):
        """No PRIVATE-TOKEN header when token is empty."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="1", token=""
        )
        headers = fetcher._headers()
        assert "PRIVATE-TOKEN" not in headers

    def test_properties_expose_resolved_values(self):
        """Properties api_url, project_id, has_token expose config."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="tok"
        )
        assert fetcher.api_url == "https://gl.test"
        assert fetcher.project_id == "42"
        assert fetcher.has_token is True

    def test_has_token_false_when_empty(self):
        """has_token is False when no token configured."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="1", token=""
        )
        assert fetcher.has_token is False

    def test_trailing_slash_stripped(self):
        """Trailing slash on api_url is stripped."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test/", project_id="1", token=""
        )
        assert fetcher.api_url == "https://gl.test"


# ---------------------------------------------------------------------------
# GitLabArtifactFetcher: check_connection
# ---------------------------------------------------------------------------


class TestCheckConnection:
    """Tests for GitLab connectivity check."""

    def setup_method(self):
        self.fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="tok"
        )

    @patch("scripts.sync_ci_results.requests.get")
    def test_connection_ok(self, mock_get):
        """Returns ok=True when API responds with project info."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 42,
            "path_with_namespace": "group/project",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = self.fetcher.check_connection()
        assert result["ok"] is True
        assert result["project_name"] == "group/project"
        assert result["error"] is None

    @patch("scripts.sync_ci_results.requests.get")
    def test_connection_auth_failure(self, mock_get):
        """Returns error on 401 Unauthorized."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        result = self.fetcher.check_connection()
        assert result["ok"] is False
        assert "Authentication failed" in result["error"]

    @patch("scripts.sync_ci_results.requests.get")
    def test_connection_project_not_found(self, mock_get):
        """Returns error on 404 Not Found."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        result = self.fetcher.check_connection()
        assert result["ok"] is False
        assert "not found" in result["error"]

    @patch("scripts.sync_ci_results.requests.get")
    def test_connection_unreachable(self, mock_get):
        """Returns error when host is unreachable."""
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        result = self.fetcher.check_connection()
        assert result["ok"] is False
        assert "Cannot connect" in result["error"]

    @patch("scripts.sync_ci_results.requests.get")
    def test_connection_includes_config_info(self, mock_get):
        """Result includes api_url, project_id, has_token."""
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        result = self.fetcher.check_connection()
        assert result["api_url"] == "https://gl.test"
        assert result["project_id"] == "42"
        assert result["has_token"] is True


# ---------------------------------------------------------------------------
# GitLabArtifactFetcher: fetch_recent_pipelines
# ---------------------------------------------------------------------------


class TestFetchRecentPipelines:
    """Tests for fetching recent pipelines from GitLab API."""

    def setup_method(self):
        self.fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="tok"
        )

    @patch("scripts.sync_ci_results.requests.get")
    def test_fetch_recent_pipelines_success(self, mock_get):
        """Returns list of pipeline dicts from GitLab API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": 500,
                "ref": "main",
                "sha": "abc123",
                "status": "success",
                "web_url": "https://gl.test/p/500",
            },
            {
                "id": 501,
                "ref": "main",
                "sha": "def456",
                "status": "success",
                "web_url": "https://gl.test/p/501",
            },
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        pipelines = self.fetcher.fetch_recent_pipelines(limit=10)
        assert len(pipelines) == 2
        assert pipelines[0]["id"] == 500

        # Verify API URL construction
        call_url = mock_get.call_args[0][0]
        assert "/api/v4/projects/42/pipelines" in call_url
        assert "status=success" in call_url

    @patch("scripts.sync_ci_results.requests.get")
    def test_fetch_recent_pipelines_with_ref_filter(self, mock_get):
        """Filters pipelines by branch ref."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        self.fetcher.fetch_recent_pipelines(ref="main", limit=5)
        call_url = mock_get.call_args[0][0]
        assert "ref=main" in call_url

    @patch("scripts.sync_ci_results.requests.get")
    def test_fetch_recent_pipelines_handles_api_error(self, mock_get):
        """Returns empty list on API error."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        pipelines = self.fetcher.fetch_recent_pipelines()
        assert pipelines == []

    @patch("scripts.sync_ci_results.requests.get")
    def test_fetch_pipelines_custom_status(self, mock_get):
        """Supports filtering by pipeline status other than success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        self.fetcher.fetch_recent_pipelines(status="failed", limit=5)
        call_url = mock_get.call_args[0][0]
        assert "status=failed" in call_url


# ---------------------------------------------------------------------------
# GitLabArtifactFetcher: fetch_pipeline_jobs
# ---------------------------------------------------------------------------


class TestFetchPipelineJobs:
    """Tests for fetching jobs from a pipeline."""

    def setup_method(self):
        self.fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="tok"
        )

    @patch("scripts.sync_ci_results.requests.get")
    def test_fetch_jobs_success(self, mock_get):
        """Returns list of job dicts from GitLab API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
            {"id": 1002, "name": "test-docker", "status": "success"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        jobs = self.fetcher.fetch_pipeline_jobs(pipeline_id=500)
        assert len(jobs) == 2
        assert jobs[0]["id"] == 1001

    @patch("scripts.sync_ci_results.requests.get")
    def test_fetch_jobs_returns_empty_on_404(self, mock_get):
        """Returns empty list when pipeline not found."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        jobs = self.fetcher.fetch_pipeline_jobs(pipeline_id=999)
        assert jobs == []

    @patch("scripts.sync_ci_results.requests.get")
    def test_fetch_jobs_includes_pipeline_id_in_url(self, mock_get):
        """API URL includes the pipeline ID."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        self.fetcher.fetch_pipeline_jobs(pipeline_id=777)
        call_url = mock_get.call_args[0][0]
        assert "/pipelines/777/jobs" in call_url


# ---------------------------------------------------------------------------
# GitLabArtifactFetcher: download_job_artifact
# ---------------------------------------------------------------------------


class TestDownloadJobArtifact:
    """Tests for downloading output.xml from job artifacts."""

    def setup_method(self):
        self.fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="tok"
        )

    @patch("scripts.sync_ci_results.requests.get")
    def test_download_artifact_success(self, mock_get):
        """Downloads artifact and writes to output directory."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<robot>test output</robot>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.fetcher.download_job_artifact(job_id=1001, output_dir=tmpdir)
            assert path is not None
            assert os.path.exists(path)
            with open(path) as f:
                assert "<robot>" in f.read()

    @patch("scripts.sync_ci_results.requests.get")
    def test_download_artifact_returns_none_on_404(self, mock_get):
        """Returns None when artifact not found."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.fetcher.download_job_artifact(job_id=1001, output_dir=tmpdir)
            assert path is None

    @patch("scripts.sync_ci_results.requests.get")
    def test_download_artifact_custom_path(self, mock_get):
        """Downloads a non-default artifact path."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html>report</html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.fetcher.download_job_artifact(
                job_id=1001, output_dir=tmpdir, artifact_path="results/log.html"
            )
            assert path is not None
            call_url = mock_get.call_args[0][0]
            assert "/artifacts/results/log.html" in call_url

    @patch("scripts.sync_ci_results.requests.get")
    def test_download_artifact_filename_includes_job_id(self, mock_get):
        """Output filename includes job ID to avoid collisions."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"data"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.fetcher.download_job_artifact(job_id=9999, output_dir=tmpdir)
            assert "9999" in os.path.basename(path)


# ---------------------------------------------------------------------------
# sync_ci_results: end-to-end sync workflow
# ---------------------------------------------------------------------------


class TestSyncCiResults:
    """Tests for the end-to-end sync workflow."""

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_fetches_and_imports(self, mock_import):
        """Full sync flow: fetch pipelines -> jobs -> artifacts -> import."""
        mock_import.return_value = 1

        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {
                "id": 500,
                "ref": "main",
                "sha": "abc123",
                "web_url": "https://gl.test/p/500",
            },
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
        ]
        fetcher.download_job_artifact.return_value = "/tmp/output.xml"

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db, pipeline_limit=1)
        assert result["runs_imported"] >= 1
        assert result["pipelines_checked"] == 1
        mock_import.assert_called_once()

    def test_sync_skips_already_imported_pipelines(self):
        """Skips pipelines whose URL already exists in recent runs."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]

        db = MagicMock()
        db.get_recent_runs.return_value = [
            {"pipeline_url": "https://gl.test/p/500"},
        ]

        result = sync_ci_results(fetcher, db)
        assert result["runs_imported"] == 0
        fetcher.fetch_pipeline_jobs.assert_not_called()

    def test_sync_dedup_uses_pipeline_url_key(self):
        """Deduplication reads 'pipeline_url' (not legacy 'gitlab_pipeline_url')."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]

        db = MagicMock()
        # Simulate DB returning the correct key
        db.get_recent_runs.return_value = [
            {"pipeline_url": "https://gl.test/p/500", "model_name": "llama3"},
        ]

        result = sync_ci_results(fetcher, db)
        assert result["pipelines_checked"] == 1
        assert result["runs_imported"] == 0
        fetcher.fetch_pipeline_jobs.assert_not_called()

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_handles_download_failure(self, mock_import):
        """Continues when artifact download fails for a job."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
        ]
        fetcher.download_job_artifact.return_value = None

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db)
        assert result["runs_imported"] == 0
        mock_import.assert_not_called()

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_returns_counts(self, mock_import):
        """Returns accurate counts of checked/downloaded/imported."""
        mock_import.return_value = 1

        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
            {"id": 501, "web_url": "https://gl.test/p/501"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
        ]
        fetcher.download_job_artifact.return_value = "/tmp/output.xml"

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db, pipeline_limit=2)
        assert result["pipelines_checked"] == 2
        assert result["artifacts_downloaded"] == 2
        assert result["runs_imported"] == 2

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_records_import_errors(self, mock_import):
        """Import exceptions are captured in errors list."""
        mock_import.side_effect = Exception("parse failed")

        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
        ]
        fetcher.download_job_artifact.return_value = "/tmp/output.xml"

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db, pipeline_limit=1)
        assert result["artifacts_downloaded"] == 1
        assert result["runs_imported"] == 0
        assert len(result["errors"]) == 1
        assert "1001" in result["errors"][0]

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_processes_multiple_jobs_per_pipeline(self, mock_import):
        """All jobs in a pipeline are processed."""
        mock_import.return_value = 1

        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
            {"id": 1002, "name": "test-docker", "status": "success"},
            {"id": 1003, "name": "test-safety", "status": "success"},
        ]
        fetcher.download_job_artifact.return_value = "/tmp/output.xml"

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db, pipeline_limit=1)
        assert result["artifacts_downloaded"] == 3
        assert result["runs_imported"] == 3

    def test_sync_with_no_pipelines(self):
        """Returns zero counts when no pipelines found."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = []

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db)
        assert result["pipelines_checked"] == 0
        assert result["artifacts_downloaded"] == 0
        assert result["runs_imported"] == 0


# ---------------------------------------------------------------------------
# verify_sync
# ---------------------------------------------------------------------------


class TestVerifySync:
    """Tests for database verification after sync."""

    def test_verify_returns_true_when_data_exists(self):
        """Verification passes when recent runs exist in the database."""
        db = MagicMock()
        db.get_recent_runs.return_value = [
            {
                "id": 1,
                "timestamp": "2025-01-01T00:00:00",
                "model_name": "llama3",
            },
        ]
        result = verify_sync(db, min_runs=1)
        assert result["success"] is True
        assert result["recent_runs"] == 1
        assert "llama3" in result["models_found"]

    def test_verify_returns_false_when_empty(self):
        """Verification fails when no runs exist."""
        db = MagicMock()
        db.get_recent_runs.return_value = []
        result = verify_sync(db)
        assert result["success"] is False
        assert result["recent_runs"] == 0

    def test_verify_reports_latest_timestamp(self):
        """Returns the most recent timestamp from the database."""
        db = MagicMock()
        db.get_recent_runs.return_value = [
            {
                "id": 2,
                "timestamp": "2025-06-15T10:00:00",
                "model_name": "mistral",
            },
            {
                "id": 1,
                "timestamp": "2025-06-14T10:00:00",
                "model_name": "llama3",
            },
        ]
        result = verify_sync(db, min_runs=1)
        assert result["success"] is True
        assert result["latest_timestamp"] == "2025-06-15T10:00:00"
        assert len(result["models_found"]) == 2

    def test_verify_min_runs_threshold(self):
        """Fails when fewer runs than min_runs exist."""
        db = MagicMock()
        db.get_recent_runs.return_value = [
            {"id": 1, "timestamp": "2025-01-01", "model_name": "llama3"},
        ]
        result = verify_sync(db, min_runs=5)
        assert result["success"] is False

    def test_verify_null_timestamp_handled(self):
        """Handles None timestamp gracefully."""
        db = MagicMock()
        db.get_recent_runs.return_value = []
        result = verify_sync(db)
        assert result["latest_timestamp"] is None


# ---------------------------------------------------------------------------
# CLI subcommand handlers
# ---------------------------------------------------------------------------


class TestCmdStatus:
    """Tests for the status subcommand."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_status_ok(self, mock_make, capsys):
        """Prints config and exits 0 on success."""
        fetcher = MagicMock()
        fetcher.check_connection.return_value = {
            "ok": True,
            "api_url": "https://gl.test",
            "project_id": "42",
            "has_token": True,
            "error": None,
            "project_name": "group/project",
        }
        mock_make.return_value = fetcher

        with pytest.raises(SystemExit) as exc_info:
            cmd_status(argparse.Namespace())
        assert exc_info.value.code == 0

        out = capsys.readouterr().out
        assert "OK" in out
        assert "group/project" in out

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_status_failure(self, mock_make, capsys):
        """Prints error and exits 1 on failure."""
        fetcher = MagicMock()
        fetcher.check_connection.return_value = {
            "ok": False,
            "api_url": "https://gl.test",
            "project_id": "42",
            "has_token": False,
            "error": "Authentication failed",
            "project_name": None,
        }
        mock_make.return_value = fetcher

        with pytest.raises(SystemExit) as exc_info:
            cmd_status(argparse.Namespace())
        assert exc_info.value.code == 1

        out = capsys.readouterr().out
        assert "FAILED" in out
        assert "Authentication failed" in out


class TestCmdListPipelines:
    """Tests for the list-pipelines subcommand."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_pipelines_output(self, mock_make, capsys):
        """Prints formatted pipeline table."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {
                "id": 500,
                "status": "success",
                "ref": "main",
                "sha": "abc12345def",
                "web_url": "https://gl.test/p/500",
            },
        ]
        mock_make.return_value = fetcher

        args = argparse.Namespace(ref=None, status="success", limit=10)
        cmd_list_pipelines(args)

        out = capsys.readouterr().out
        assert "500" in out
        assert "success" in out
        assert "main" in out

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_pipelines_empty(self, mock_make, capsys):
        """Prints message when no pipelines found."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = []
        mock_make.return_value = fetcher

        args = argparse.Namespace(ref=None, status="success", limit=10)
        with pytest.raises(SystemExit) as exc_info:
            cmd_list_pipelines(args)
        assert exc_info.value.code == 0

        out = capsys.readouterr().out
        assert "No pipelines found" in out


class TestCmdListJobs:
    """Tests for the list-jobs subcommand."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_jobs_output(self, mock_make, capsys):
        """Prints formatted job table."""
        fetcher = MagicMock()
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success", "duration": 120.5},
        ]
        mock_make.return_value = fetcher

        args = argparse.Namespace(pipeline_id=500, scope="success")
        cmd_list_jobs(args)

        out = capsys.readouterr().out
        assert "1001" in out
        assert "test-math" in out
        assert "120s" in out  # int(120.5) truncates

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_jobs_empty(self, mock_make, capsys):
        """Prints message when no jobs found."""
        fetcher = MagicMock()
        fetcher.fetch_pipeline_jobs.return_value = []
        mock_make.return_value = fetcher

        args = argparse.Namespace(pipeline_id=999, scope="success")
        with pytest.raises(SystemExit) as exc_info:
            cmd_list_jobs(args)
        assert exc_info.value.code == 0

        out = capsys.readouterr().out
        assert "No jobs found" in out


class TestCmdFetchArtifact:
    """Tests for the fetch-artifact subcommand."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_fetch_artifact_success(self, mock_make, capsys):
        """Prints download path on success."""
        fetcher = MagicMock()
        mock_make.return_value = fetcher

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "job_1001_output.xml")
            fetcher.download_job_artifact.return_value = out_path

            args = argparse.Namespace(
                job_id=1001, artifact_path="output.xml", output_dir=tmpdir
            )
            cmd_fetch_artifact(args)

            out = capsys.readouterr().out
            assert "Downloaded" in out

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_fetch_artifact_not_found(self, mock_make, capsys):
        """Exits 1 when artifact not found."""
        fetcher = MagicMock()
        fetcher.download_job_artifact.return_value = None
        mock_make.return_value = fetcher

        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                job_id=1001, artifact_path="output.xml", output_dir=tmpdir
            )
            with pytest.raises(SystemExit) as exc_info:
                cmd_fetch_artifact(args)
            assert exc_info.value.code == 1


class TestCmdSync:
    """Tests for the sync subcommand."""

    @patch("scripts.sync_ci_results.sync_ci_results")
    @patch("scripts.sync_ci_results._make_db")
    @patch("scripts.sync_ci_results._make_fetcher")
    def test_sync_prints_counts(self, mock_fetcher, mock_db, mock_sync, capsys):
        """Prints sync result counts."""
        mock_sync.return_value = {
            "pipelines_checked": 3,
            "artifacts_downloaded": 2,
            "runs_imported": 2,
            "errors": [],
        }

        args = argparse.Namespace(
            db=None, limit=5, ref=None, dry_run=False
        )
        cmd_sync(args)

        out = capsys.readouterr().out
        assert "Pipelines checked: 3" in out
        assert "Artifacts downloaded: 2" in out
        assert "Runs imported: 2" in out

    @patch("scripts.sync_ci_results.sync_ci_results")
    @patch("scripts.sync_ci_results._make_db")
    @patch("scripts.sync_ci_results._make_fetcher")
    def test_sync_exits_1_on_errors(self, mock_fetcher, mock_db, mock_sync):
        """Exits 1 when sync has errors."""
        mock_sync.return_value = {
            "pipelines_checked": 1,
            "artifacts_downloaded": 1,
            "runs_imported": 0,
            "errors": ["Failed to import job 1001: parse error"],
        }

        args = argparse.Namespace(
            db=None, limit=5, ref=None, dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_sync(args)
        assert exc_info.value.code == 1

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_sync_dry_run(self, mock_make, capsys):
        """Dry run lists pipelines without importing."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "ref": "main", "web_url": "https://gl.test/p/500"},
        ]
        mock_make.return_value = fetcher

        args = argparse.Namespace(
            db=None, limit=5, ref=None, dry_run=True
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_sync(args)
        assert exc_info.value.code == 0

        out = capsys.readouterr().out
        assert "Would sync 1 pipeline(s)" in out


class TestCmdVerify:
    """Tests for the verify subcommand."""

    @patch("scripts.sync_ci_results._make_db")
    def test_verify_pass(self, mock_make_db, capsys):
        """Prints PASS and exits 0 when data exists."""
        db = MagicMock()
        db.get_recent_runs.return_value = [
            {"id": 1, "timestamp": "2025-01-01", "model_name": "llama3"},
        ]
        mock_make_db.return_value = db

        args = argparse.Namespace(db=None)
        with pytest.raises(SystemExit) as exc_info:
            cmd_verify(args)
        assert exc_info.value.code == 0

        out = capsys.readouterr().out
        assert "PASS" in out

    @patch("scripts.sync_ci_results._make_db")
    def test_verify_fail(self, mock_make_db, capsys):
        """Prints FAIL and exits 1 when empty."""
        db = MagicMock()
        db.get_recent_runs.return_value = []
        mock_make_db.return_value = db

        args = argparse.Namespace(db=None)
        with pytest.raises(SystemExit) as exc_info:
            cmd_verify(args)
        assert exc_info.value.code == 1

        out = capsys.readouterr().out
        assert "FAIL" in out
