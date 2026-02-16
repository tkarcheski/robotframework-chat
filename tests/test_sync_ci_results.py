"""Tests for CI pipeline results sync to database.

Expanded coverage: 51 tests across GitLabArtifactFetcher init/properties,
check_connection, pipeline/job/artifact fetching, end-to-end sync workflow,
verify_sync, and all 6 CLI subcommand handlers.
"""

import argparse
import logging
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.sync_ci_results import (
    GitLabArtifactFetcher,
    _cmd_fetch_artifact,
    _cmd_list_jobs,
    _cmd_list_pipelines,
    _cmd_status,
    _cmd_sync,
    _cmd_verify,
    _make_db,
    _make_fetcher,
    sync_ci_results,
    verify_sync,
)


# ── GitLabArtifactFetcher init, properties, trailing slash (9 tests) ─


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

    def test_api_url_property(self):
        """api_url property exposes the resolved URL."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="t"
        )
        assert fetcher.api_url == "https://gl.test"

    def test_project_id_property(self):
        """project_id property exposes the resolved project ID."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="t"
        )
        assert fetcher.project_id == "42"

    def test_trailing_slash_stripped(self):
        """Trailing slash is stripped from api_url."""
        fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test/", project_id="1", token=""
        )
        assert fetcher.api_url == "https://gl.test"


# ── check_connection with OK, 401, 404, unreachable (5 tests) ────────


class TestCheckConnection:
    """Tests for check_connection method."""

    def setup_method(self):
        self.fetcher = GitLabArtifactFetcher(
            api_url="https://gl.test", project_id="42", token="tok"
        )

    @patch("scripts.sync_ci_results.requests.get")
    def test_check_connection_ok(self, mock_get):
        """Returns ok=True on 200."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name_with_namespace": "user/project"}
        mock_get.return_value = mock_resp

        result = self.fetcher.check_connection()
        assert result["ok"] is True
        assert result["status_code"] == 200
        assert "user/project" in result["message"]

    @patch("scripts.sync_ci_results.requests.get")
    def test_check_connection_401(self, mock_get):
        """Returns ok=False on 401 Unauthorized."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        result = self.fetcher.check_connection()
        assert result["ok"] is False
        assert result["status_code"] == 401
        assert "401" in result["message"]

    @patch("scripts.sync_ci_results.requests.get")
    def test_check_connection_404(self, mock_get):
        """Returns ok=False on 404 Not Found."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = self.fetcher.check_connection()
        assert result["ok"] is False
        assert result["status_code"] == 404

    @patch("scripts.sync_ci_results.requests.get")
    def test_check_connection_unreachable(self, mock_get):
        """Returns ok=False with status_code=0 on network error."""
        mock_get.side_effect = requests.exceptions.ConnectionError("DNS failed")

        result = self.fetcher.check_connection()
        assert result["ok"] is False
        assert result["status_code"] == 0
        assert "Unreachable" in result["message"]

    @patch("scripts.sync_ci_results.requests.get")
    def test_check_connection_logs_warning(self, mock_get, caplog):
        """Logs a warning on network failure."""
        mock_get.side_effect = requests.exceptions.ConnectionError("timeout")

        with caplog.at_level(logging.WARNING, logger="scripts.sync_ci_results"):
            self.fetcher.check_connection()
        assert "Connection check failed" in caplog.text


# ── Pipeline/job/artifact fetching (11 tests) ────────────────────────


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
    def test_fetch_pipelines_logs_warning_on_error(self, mock_get, caplog):
        """Logs warning when fetch fails."""
        mock_get.side_effect = requests.exceptions.ConnectionError("fail")

        with caplog.at_level(logging.WARNING, logger="scripts.sync_ci_results"):
            self.fetcher.fetch_recent_pipelines()
        assert "Failed to fetch pipelines" in caplog.text


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
    def test_fetch_jobs_logs_warning_on_error(self, mock_get, caplog):
        """Logs warning when fetch fails."""
        mock_get.side_effect = requests.exceptions.ConnectionError("fail")

        with caplog.at_level(logging.WARNING, logger="scripts.sync_ci_results"):
            self.fetcher.fetch_pipeline_jobs(pipeline_id=500)
        assert "Failed to fetch jobs for pipeline 500" in caplog.text


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
    def test_download_artifact_sanitizes_slashes(self, mock_get):
        """Artifact path with / is sanitized to _ in filename."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html>log</html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.fetcher.download_job_artifact(
                job_id=1001, output_dir=tmpdir, artifact_path="results/log.html"
            )
            assert path is not None
            assert "results_log.html" in os.path.basename(path)
            assert os.path.exists(path)

    @patch("scripts.sync_ci_results.requests.get")
    def test_download_artifact_logs_debug_on_failure(self, mock_get, caplog):
        """Logs debug message when artifact download fails."""
        mock_get.side_effect = requests.exceptions.ConnectionError("fail")

        with caplog.at_level(logging.DEBUG, logger="scripts.sync_ci_results"):
            with tempfile.TemporaryDirectory() as tmpdir:
                self.fetcher.download_job_artifact(job_id=1001, output_dir=tmpdir)
        assert "Artifact download failed for job 1001" in caplog.text


# ── End-to-end sync workflow (8 tests) ───────────────────────────────


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

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_handles_download_failure(self, mock_import):
        """Continues when artifact download fails for all paths in a job."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
        ]
        # None for every artifact path tried
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
        """Records import errors in result dict."""
        mock_import.side_effect = RuntimeError("bad xml")

        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test", "status": "success"},
        ]
        fetcher.download_job_artifact.return_value = "/tmp/output.xml"

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db)
        assert result["runs_imported"] == 0
        assert len(result["errors"]) == 1
        assert "1001" in result["errors"][0]

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_multi_job_pipeline(self, mock_import):
        """Handles pipelines with multiple jobs."""
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

        result = sync_ci_results(fetcher, db)
        assert result["artifacts_downloaded"] == 3
        assert result["runs_imported"] == 3

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_no_pipelines_returns_zeros(self, mock_import):
        """Returns zero counts when no pipelines exist."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = []

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(fetcher, db)
        assert result["pipelines_checked"] == 0
        assert result["artifacts_downloaded"] == 0
        assert result["runs_imported"] == 0

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_mixed_download_success_and_failure(self, mock_import):
        """Counts only successfully downloaded artifacts."""
        mock_import.return_value = 1

        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "has-artifact", "status": "success"},
            {"id": 1002, "name": "no-artifact", "status": "success"},
        ]
        # Use a single path list so each job gets exactly one try
        # Job 1001 succeeds on first path, job 1002 fails
        fetcher.download_job_artifact.side_effect = ["/tmp/output.xml", None]

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(
            fetcher, db, artifact_paths=["output.xml"]
        )
        assert result["artifacts_downloaded"] == 1
        assert result["runs_imported"] == 1

    @patch("scripts.sync_ci_results.import_results")
    def test_sync_tries_multiple_artifact_paths(self, mock_import):
        """Falls back to alternative artifact paths when first path fails."""
        mock_import.return_value = 1

        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "web_url": "https://gl.test/p/500"},
        ]
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "name": "test-math", "status": "success"},
        ]
        # First path fails (output.xml), second succeeds (results/math/output.xml)
        fetcher.download_job_artifact.side_effect = [None, "/tmp/output.xml"]

        db = MagicMock()
        db.get_recent_runs.return_value = []

        result = sync_ci_results(
            fetcher,
            db,
            artifact_paths=["output.xml", "results/math/output.xml"],
        )
        assert result["artifacts_downloaded"] == 1
        assert result["runs_imported"] == 1
        assert fetcher.download_job_artifact.call_count == 2


# ── verify_sync including threshold, null timestamp (5 tests) ────────


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

    def test_verify_threshold_not_met(self):
        """Fails when fewer runs exist than the threshold."""
        db = MagicMock()
        db.get_recent_runs.return_value = [
            {"id": 1, "timestamp": "2025-01-01T00:00:00", "model_name": "llama3"},
        ]
        result = verify_sync(db, min_runs=5)
        assert result["success"] is False
        assert result["recent_runs"] == 1

    def test_verify_null_timestamp_handled(self):
        """Returns None for latest_timestamp when timestamp is None."""
        db = MagicMock()
        db.get_recent_runs.return_value = [
            {"id": 1, "timestamp": None, "model_name": "llama3"},
        ]
        result = verify_sync(db, min_runs=1)
        assert result["latest_timestamp"] is None


# ── CLI subcommand handlers (13 tests) ───────────────────────────────


class TestCmdStatus:
    """Tests for the status subcommand handler."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_status_ok(self, mock_mf, capsys):
        """Prints connection info and exits 0 on success."""
        fetcher = MagicMock()
        fetcher.api_url = "https://gl.test"
        fetcher.project_id = "42"
        fetcher.has_token = True
        fetcher.check_connection.return_value = {
            "ok": True,
            "status_code": 200,
            "message": "Connected to user/project",
        }
        mock_mf.return_value = fetcher

        with pytest.raises(SystemExit) as exc:
            _cmd_status(argparse.Namespace())
        assert exc.value.code == 0

        out = capsys.readouterr().out
        assert "https://gl.test" in out
        assert "OK" in out

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_status_fail(self, mock_mf, capsys):
        """Exits 1 on connection failure."""
        fetcher = MagicMock()
        fetcher.api_url = "https://gl.test"
        fetcher.project_id = "42"
        fetcher.has_token = False
        fetcher.check_connection.return_value = {
            "ok": False,
            "status_code": 401,
            "message": "HTTP 401",
        }
        mock_mf.return_value = fetcher

        with pytest.raises(SystemExit) as exc:
            _cmd_status(argparse.Namespace())
        assert exc.value.code == 1

        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "NOT set" in out


class TestCmdListPipelines:
    """Tests for the list-pipelines subcommand handler."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_pipelines_output(self, mock_mf, capsys):
        """Prints pipeline table."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = [
            {"id": 500, "status": "success", "ref": "main", "web_url": "https://gl/500"},
        ]
        mock_mf.return_value = fetcher

        args = argparse.Namespace(ref=None, limit=10)
        _cmd_list_pipelines(args)

        out = capsys.readouterr().out
        assert "500" in out
        assert "success" in out

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_pipelines_empty(self, mock_mf, capsys):
        """Prints message when no pipelines found."""
        fetcher = MagicMock()
        fetcher.fetch_recent_pipelines.return_value = []
        mock_mf.return_value = fetcher

        args = argparse.Namespace(ref=None, limit=10)
        _cmd_list_pipelines(args)

        out = capsys.readouterr().out
        assert "No pipelines found" in out


class TestCmdListJobs:
    """Tests for the list-jobs subcommand handler."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_jobs_output(self, mock_mf, capsys):
        """Prints job table."""
        fetcher = MagicMock()
        fetcher.fetch_pipeline_jobs.return_value = [
            {"id": 1001, "status": "success", "name": "test-math"},
        ]
        mock_mf.return_value = fetcher

        args = argparse.Namespace(pipeline_id=500, scope="success")
        _cmd_list_jobs(args)

        out = capsys.readouterr().out
        assert "1001" in out
        assert "test-math" in out

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_list_jobs_empty(self, mock_mf, capsys):
        """Prints message when no jobs found."""
        fetcher = MagicMock()
        fetcher.fetch_pipeline_jobs.return_value = []
        mock_mf.return_value = fetcher

        args = argparse.Namespace(pipeline_id=500, scope="success")
        _cmd_list_jobs(args)

        out = capsys.readouterr().out
        assert "No jobs found" in out


class TestCmdFetchArtifact:
    """Tests for the fetch-artifact subcommand handler."""

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_fetch_artifact_success(self, mock_mf, capsys):
        """Prints download path on success."""
        fetcher = MagicMock()
        fetcher.download_job_artifact.return_value = "/tmp/job_1001_output.xml"
        mock_mf.return_value = fetcher

        args = argparse.Namespace(
            job_id=1001, artifact_path="output.xml", output="/tmp"
        )
        _cmd_fetch_artifact(args)

        out = capsys.readouterr().out
        assert "Downloaded" in out

    @patch("scripts.sync_ci_results._make_fetcher")
    def test_fetch_artifact_not_found(self, mock_mf, capsys):
        """Exits 1 when artifact not found."""
        fetcher = MagicMock()
        fetcher.download_job_artifact.return_value = None
        mock_mf.return_value = fetcher

        args = argparse.Namespace(
            job_id=1001, artifact_path="output.xml", output=None
        )
        with pytest.raises(SystemExit) as exc:
            _cmd_fetch_artifact(args)
        assert exc.value.code == 1


class TestCmdSync:
    """Tests for the sync subcommand handler."""

    @patch("scripts.sync_ci_results.verify_sync")
    @patch("scripts.sync_ci_results.sync_ci_results")
    @patch("scripts.sync_ci_results._make_db")
    @patch("scripts.sync_ci_results._make_fetcher")
    def test_sync_success(self, mock_mf, mock_mdb, mock_sync, mock_verify, capsys):
        """Prints sync summary on success."""
        mock_mf.return_value = MagicMock()
        mock_mdb.return_value = MagicMock()
        mock_sync.return_value = {
            "pipelines_checked": 5,
            "artifacts_downloaded": 3,
            "runs_imported": 3,
            "errors": [],
        }
        mock_verify.return_value = {"success": True}

        args = argparse.Namespace(limit=5, ref=None, db=None)
        _cmd_sync(args)

        out = capsys.readouterr().out
        assert "Sync complete" in out
        assert "PASS" in out

    @patch("scripts.sync_ci_results.sync_ci_results")
    @patch("scripts.sync_ci_results._make_db")
    @patch("scripts.sync_ci_results._make_fetcher")
    def test_sync_with_errors_exits_1(self, mock_mf, mock_mdb, mock_sync, capsys):
        """Exits 1 when sync has errors."""
        mock_mf.return_value = MagicMock()
        mock_mdb.return_value = MagicMock()
        mock_sync.return_value = {
            "pipelines_checked": 1,
            "artifacts_downloaded": 1,
            "runs_imported": 0,
            "errors": ["Failed to import job 1001: bad xml"],
        }

        args = argparse.Namespace(limit=5, ref=None, db=None)
        with pytest.raises(SystemExit) as exc:
            _cmd_sync(args)
        assert exc.value.code == 1


class TestCmdVerify:
    """Tests for the verify subcommand handler."""

    @patch("scripts.sync_ci_results.verify_sync")
    @patch("scripts.sync_ci_results._make_db")
    def test_verify_pass(self, mock_mdb, mock_vs, capsys):
        """Exits 0 when verification passes."""
        mock_mdb.return_value = MagicMock()
        mock_vs.return_value = {
            "success": True,
            "recent_runs": 5,
            "latest_timestamp": "2025-06-15T10:00:00",
            "models_found": ["llama3"],
        }

        args = argparse.Namespace(db=None, min_runs=1)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == 0

        out = capsys.readouterr().out
        assert "PASS" in out

    @patch("scripts.sync_ci_results.verify_sync")
    @patch("scripts.sync_ci_results._make_db")
    def test_verify_fail(self, mock_mdb, mock_vs, capsys):
        """Exits 1 when verification fails."""
        mock_mdb.return_value = MagicMock()
        mock_vs.return_value = {
            "success": False,
            "recent_runs": 0,
            "latest_timestamp": None,
            "models_found": [],
        }

        args = argparse.Namespace(db=None, min_runs=1)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == 1


# ── Helper function tests ────────────────────────────────────────────


class TestMakeFetcher:
    """Tests for the _make_fetcher helper."""

    @patch.dict(
        os.environ,
        {"GITLAB_API_URL": "https://gl.test", "GITLAB_PROJECT_ID": "1"},
        clear=True,
    )
    def test_make_fetcher_success(self):
        """Returns a fetcher when config is available."""
        fetcher = _make_fetcher()
        assert fetcher.api_url == "https://gl.test"

    @patch.dict(os.environ, {}, clear=True)
    def test_make_fetcher_exits_on_error(self):
        """Exits 1 when no config is available."""
        with pytest.raises(SystemExit) as exc:
            _make_fetcher()
        assert exc.value.code == 1


class TestMakeDb:
    """Tests for the _make_db helper."""

    def test_make_db_with_path(self):
        """Creates TestDatabase with explicit path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            args = argparse.Namespace(db=db_path)
            db = _make_db(args)
            assert db.db_path == db_path

    def test_make_db_without_path(self):
        """Creates TestDatabase with default path."""
        args = argparse.Namespace(db=None)
        db = _make_db(args)
        assert db.db_path is not None
