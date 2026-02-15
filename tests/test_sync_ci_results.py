"""Tests for CI pipeline results sync to database."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.sync_ci_results import (
    GitLabArtifactFetcher,
    sync_ci_results,
    verify_sync,
)


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
            {"gitlab_pipeline_url": "https://gl.test/p/500"},
        ]

        result = sync_ci_results(fetcher, db)
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
