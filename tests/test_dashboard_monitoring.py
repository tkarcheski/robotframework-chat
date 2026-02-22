"""Tests for dashboard monitoring module (Ollama + GitLab)."""

import os
from unittest.mock import MagicMock, patch

from dashboard.monitoring import (
    JobInfo,
    OllamaMonitor,
    PipelineInfo,
    PipelineMonitor,
    _detect_gitlab_from_git_remote,
    _format_duration,
    build_job_table,
    build_ollama_cards,
    build_pipeline_table,
)


# ---------------------------------------------------------------------------
# OllamaMonitor
# ---------------------------------------------------------------------------


class TestOllamaMonitor:
    """Tests for OllamaMonitor polling and status tracking."""

    def setup_method(self):
        """Reset singleton between tests."""
        OllamaMonitor._instance = None

    @patch("dashboard.monitoring._node_list")
    @patch("dashboard.monitoring.requests.get")
    def test_poll_marks_reachable_host(self, mock_get, mock_nodes):
        mock_nodes.return_value = [{"hostname": "testhost", "port": 11434}]

        # /api/tags returns 200, /api/ps returns 200 with models
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "/api/tags" in url:
                resp.json.return_value = {"models": []}
            elif "/api/ps" in url:
                resp.json.return_value = {"models": []}
            return resp

        mock_get.side_effect = side_effect

        monitor = OllamaMonitor()
        # Wait for the background thread to finish
        import time

        time.sleep(0.5)

        snap = monitor.latest("testhost")
        assert snap is not None
        assert snap.reachable is True
        assert snap.error == ""

    @patch("dashboard.monitoring._node_list")
    @patch("dashboard.monitoring.requests.get")
    def test_poll_marks_unreachable_host(self, mock_get, mock_nodes):
        mock_nodes.return_value = [{"hostname": "badhost", "port": 11434}]
        mock_get.side_effect = Exception("Connection refused")

        monitor = OllamaMonitor()
        import time

        time.sleep(0.5)

        snap = monitor.latest("badhost")
        assert snap is not None
        assert snap.reachable is False
        assert snap.error != ""

    @patch("dashboard.monitoring._node_list")
    @patch("dashboard.monitoring.requests.get")
    def test_poll_records_running_models(self, mock_get, mock_nodes):
        mock_nodes.return_value = [{"hostname": "busyhost", "port": 11434}]

        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "/api/tags" in url:
                resp.json.return_value = {"models": []}
            elif "/api/ps" in url:
                resp.json.return_value = {
                    "models": [{"name": "llama3", "size_vram": 1024}]
                }
            return resp

        mock_get.side_effect = side_effect

        monitor = OllamaMonitor()
        import time

        time.sleep(0.5)

        snap = monitor.latest("busyhost")
        assert snap is not None
        assert snap.reachable is True
        assert len(snap.running_models) == 1
        assert snap.running_models[0]["name"] == "llama3"

    @patch("dashboard.monitoring._node_list")
    @patch("dashboard.monitoring.requests.get")
    def test_node_names(self, mock_get, mock_nodes):
        mock_nodes.return_value = [
            {"hostname": "host1", "port": 11434},
            {"hostname": "host2", "port": 11434},
        ]
        mock_get.side_effect = Exception("skip")

        monitor = OllamaMonitor()
        assert monitor.node_names() == ["host1", "host2"]

    @patch("dashboard.monitoring._node_list")
    @patch("dashboard.monitoring.requests.get")
    def test_force_poll(self, mock_get, mock_nodes):
        mock_nodes.return_value = [{"hostname": "h1", "port": 11434}]
        mock_get.side_effect = Exception("down")

        monitor = OllamaMonitor()
        import time

        time.sleep(0.5)

        # Force another poll
        monitor.force_poll()
        history = monitor.history("h1")
        assert len(history) >= 2


# ---------------------------------------------------------------------------
# PipelineMonitor
# ---------------------------------------------------------------------------


class TestPipelineMonitor:
    """Tests for PipelineMonitor GitLab API integration."""

    def setup_method(self):
        PipelineMonitor._instance = None

    @patch("dashboard.monitoring._detect_gitlab_from_git_remote")
    @patch("dashboard.monitoring._monitoring_config")
    def test_not_configured_when_empty(self, mock_config, mock_detect):
        mock_detect.return_value = ("", "")
        mock_config.return_value = {
            "poll_interval_seconds": 30,
            "history_hours": 24,
            "gitlab_api_url": "",
            "gitlab_project_id": "",
            "gitlab_token_env": "GITLAB_TOKEN",
            "pipeline_count": 20,
            "job_count": 50,
        }
        with patch.dict(
            os.environ,
            {
                "GITLAB_API_URL": "",
                "GITLAB_PROJECT_ID": "",
                "CI_API_V4_URL": "",
                "CI_PROJECT_ID": "",
            },
            clear=False,
        ):
            monitor = PipelineMonitor()
            assert not monitor.is_configured

    @patch("dashboard.monitoring._detect_gitlab_from_git_remote")
    def test_configured_from_env(self, mock_detect):
        mock_detect.return_value = ("", "")
        with patch.dict(
            os.environ,
            {
                "GITLAB_API_URL": "https://gitlab.example.com",
                "GITLAB_PROJECT_ID": "42",
                "CI_API_V4_URL": "",
                "CI_PROJECT_ID": "",
            },
            clear=False,
        ):
            monitor = PipelineMonitor()
            assert monitor.is_configured
            assert monitor._api_url == "https://gitlab.example.com"
            assert monitor._project_id == "42"

    @patch("dashboard.monitoring._detect_gitlab_from_git_remote")
    def test_ci_env_takes_priority(self, mock_detect):
        mock_detect.return_value = ("", "")
        with patch.dict(
            os.environ,
            {
                "CI_API_V4_URL": "https://gitlab.ci.com/api/v4",
                "CI_PROJECT_ID": "99",
                "GITLAB_API_URL": "https://other.com",
                "GITLAB_PROJECT_ID": "1",
            },
            clear=False,
        ):
            monitor = PipelineMonitor()
            assert monitor.is_configured
            assert monitor._api_url == "https://gitlab.ci.com"
            assert monitor._project_id == "99"

    @patch("dashboard.monitoring.requests.get")
    @patch("dashboard.monitoring._detect_gitlab_from_git_remote")
    def test_fetch_populates_pipelines(self, mock_detect, mock_get):
        mock_detect.return_value = ("", "")
        with patch.dict(
            os.environ,
            {
                "GITLAB_API_URL": "https://gl.test",
                "GITLAB_PROJECT_ID": "10",
                "CI_API_V4_URL": "",
                "CI_PROJECT_ID": "",
            },
            clear=False,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = [
                {
                    "id": 100,
                    "status": "success",
                    "ref": "main",
                    "sha": "abcdef1234567890",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:01:00Z",
                    "web_url": "https://gl.test/p/100",
                    "source": "push",
                },
            ]
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            monitor = PipelineMonitor()
            monitor._fetch()

            assert len(monitor.pipelines) == 1
            assert monitor.pipelines[0].id == 100
            assert monitor.pipelines[0].status == "success"


# ---------------------------------------------------------------------------
# Git remote detection
# ---------------------------------------------------------------------------


class TestGitRemoteDetection:
    """Tests for _detect_gitlab_from_git_remote."""

    @patch("dashboard.monitoring.subprocess.run")
    def test_ssh_remote(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="git@gitlab.com:group/project.git\n"
        )
        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == "https://gitlab.com"
        assert path == "group/project"

    @patch("dashboard.monitoring.subprocess.run")
    def test_https_remote(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://gitlab.com/group/project.git\n"
        )
        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == "https://gitlab.com"
        assert path == "group/project"

    @patch("dashboard.monitoring.subprocess.run")
    def test_localhost_remote_skipped(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="http://127.0.0.1:1234/git/group/project\n"
        )
        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == ""
        assert path == ""

    @patch("dashboard.monitoring.subprocess.run")
    def test_no_remote(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == ""
        assert path == ""


# ---------------------------------------------------------------------------
# Layout builders
# ---------------------------------------------------------------------------


class TestBuildOllamaCards:
    """Tests for the Ollama cards layout builder."""

    @patch("dashboard.monitoring._node_list")
    @patch("dashboard.monitoring.requests.get")
    def test_returns_cards_for_each_node(self, mock_get, mock_nodes):
        OllamaMonitor._instance = None
        mock_nodes.return_value = [
            {"hostname": "a", "port": 11434},
            {"hostname": "b", "port": 11434},
        ]
        mock_get.side_effect = Exception("down")
        monitor = OllamaMonitor()
        import time

        time.sleep(0.5)

        cards = build_ollama_cards(monitor)
        assert len(cards) == 2


class TestBuildPipelineTable:
    """Tests for the pipeline table layout builder."""

    def test_empty_pipelines_shows_help(self):
        result = build_pipeline_table([])
        # Should return a Div with help text
        assert result is not None

    def test_with_pipelines_shows_table(self):
        pipes = [
            PipelineInfo(
                id=1,
                status="success",
                ref="main",
                sha="abc12345",
                created_at="2025-01-01T00:00:00Z",
                updated_at="2025-01-01T00:01:00Z",
                web_url="https://example.com/1",
                source="push",
            )
        ]
        result = build_pipeline_table(pipes)
        assert result is not None


# ---------------------------------------------------------------------------
# JobInfo dataclass
# ---------------------------------------------------------------------------


class TestJobInfo:
    """Tests for the JobInfo dataclass."""

    def test_job_info_fields(self):
        job = JobInfo(
            id=1001,
            name="test-math",
            status="success",
            duration=123.4,
            pipeline_id=500,
            pipeline_ref="main",
            pipeline_sha="abcdef12",
            web_url="https://gl.test/-/jobs/1001",
            created_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:02:03Z",
        )
        assert job.id == 1001
        assert job.name == "test-math"
        assert job.status == "success"
        assert job.duration == 123.4
        assert job.pipeline_id == 500
        assert job.artifacts_uploaded is False

    def test_job_info_artifacts_uploaded(self):
        job = JobInfo(
            id=1002,
            name="test-docker",
            status="failed",
            duration=None,
            pipeline_id=501,
            pipeline_ref="feature",
            pipeline_sha="deadbeef",
            web_url="",
            created_at="",
            finished_at="",
            artifacts_uploaded=True,
        )
        assert job.artifacts_uploaded is True
        assert job.duration is None


# ---------------------------------------------------------------------------
# _format_duration helper
# ---------------------------------------------------------------------------


class TestFormatDuration:
    """Tests for the _format_duration helper."""

    def test_none_returns_dash(self):
        assert _format_duration(None) == "-"

    def test_zero_returns_zero_s(self):
        assert _format_duration(0) == "0s"

    def test_seconds_only(self):
        assert _format_duration(45.7) == "45s"

    def test_minutes_and_seconds(self):
        assert _format_duration(95.2) == "1m 35s"

    def test_hours_minutes_seconds(self):
        assert _format_duration(3661.0) == "1h 1m 1s"

    def test_exact_minutes(self):
        assert _format_duration(120.0) == "2m"

    def test_exact_hours(self):
        assert _format_duration(7200.0) == "2h"


# ---------------------------------------------------------------------------
# Job fetching in PipelineMonitor
# ---------------------------------------------------------------------------


class TestJobFetching:
    """Tests for PipelineMonitor._fetch_jobs()."""

    def setup_method(self):
        PipelineMonitor._instance = None

    @patch("dashboard.monitoring.requests.get")
    @patch("dashboard.monitoring._detect_gitlab_from_git_remote")
    def test_fetch_jobs_populates_list(self, mock_detect, mock_get):
        mock_detect.return_value = ("", "")
        with patch.dict(
            os.environ,
            {
                "GITLAB_API_URL": "https://gl.test",
                "GITLAB_PROJECT_ID": "10",
                "CI_API_V4_URL": "",
                "CI_PROJECT_ID": "",
            },
            clear=False,
        ):
            # First call is for pipelines, second for jobs
            pipelines_resp = MagicMock()
            pipelines_resp.status_code = 200
            pipelines_resp.json.return_value = []
            pipelines_resp.raise_for_status = MagicMock()

            jobs_resp = MagicMock()
            jobs_resp.status_code = 200
            jobs_resp.json.return_value = [
                {
                    "id": 1001,
                    "name": "test-math",
                    "status": "success",
                    "duration": 95.2,
                    "pipeline": {
                        "id": 500,
                        "ref": "main",
                        "sha": "abcdef1234567890",
                        "status": "success",
                    },
                    "web_url": "https://gl.test/-/jobs/1001",
                    "created_at": "2025-01-01T00:00:00Z",
                    "finished_at": "2025-01-01T00:01:35Z",
                },
                {
                    "id": 1002,
                    "name": "test-docker",
                    "status": "failed",
                    "duration": 210.5,
                    "pipeline": {
                        "id": 500,
                        "ref": "main",
                        "sha": "abcdef1234567890",
                        "status": "failed",
                    },
                    "web_url": "https://gl.test/-/jobs/1002",
                    "created_at": "2025-01-01T00:00:00Z",
                    "finished_at": "2025-01-01T00:03:30Z",
                },
            ]
            jobs_resp.raise_for_status = MagicMock()
            mock_get.return_value = jobs_resp

            monitor = PipelineMonitor()
            monitor._fetch_jobs()

            assert len(monitor.jobs) == 2
            assert monitor.jobs[0].id == 1001
            assert monitor.jobs[0].name == "test-math"
            assert monitor.jobs[0].duration == 95.2
            assert monitor.jobs[0].pipeline_id == 500
            assert monitor.jobs[1].status == "failed"

    @patch("dashboard.monitoring.requests.get")
    @patch("dashboard.monitoring._detect_gitlab_from_git_remote")
    def test_fetch_jobs_handles_null_duration(self, mock_detect, mock_get):
        mock_detect.return_value = ("", "")
        with patch.dict(
            os.environ,
            {
                "GITLAB_API_URL": "https://gl.test",
                "GITLAB_PROJECT_ID": "10",
                "CI_API_V4_URL": "",
                "CI_PROJECT_ID": "",
            },
            clear=False,
        ):
            jobs_resp = MagicMock()
            jobs_resp.status_code = 200
            jobs_resp.json.return_value = [
                {
                    "id": 2001,
                    "name": "pending-job",
                    "status": "pending",
                    "duration": None,
                    "pipeline": {
                        "id": 600,
                        "ref": "dev",
                        "sha": "1234567890abcdef",
                        "status": "running",
                    },
                    "web_url": "",
                    "created_at": "2025-01-01T00:00:00Z",
                    "finished_at": "",
                },
            ]
            jobs_resp.raise_for_status = MagicMock()
            mock_get.return_value = jobs_resp

            monitor = PipelineMonitor()
            monitor._fetch_jobs()

            assert len(monitor.jobs) == 1
            assert monitor.jobs[0].duration is None


# ---------------------------------------------------------------------------
# Artifact upload detection
# ---------------------------------------------------------------------------


class TestArtifactDetection:
    """Tests for PipelineMonitor._is_uploaded()."""

    def test_matches_pipeline_id_suffix(self):
        monitor = PipelineMonitor.__new__(PipelineMonitor)
        monitor._uploaded_pipeline_urls = {
            "https://gitlab.example.com/group/project/-/pipelines/500",
            "https://gitlab.example.com/group/project/-/pipelines/600",
        }
        assert monitor._is_uploaded(500) is True
        assert monitor._is_uploaded(600) is True
        assert monitor._is_uploaded(999) is False

    def test_empty_set_returns_false(self):
        monitor = PipelineMonitor.__new__(PipelineMonitor)
        monitor._uploaded_pipeline_urls = set()
        assert monitor._is_uploaded(500) is False

    def test_partial_id_no_false_positive(self):
        monitor = PipelineMonitor.__new__(PipelineMonitor)
        monitor._uploaded_pipeline_urls = {
            "https://gitlab.example.com/group/project/-/pipelines/1500",
        }
        # 500 should NOT match 1500
        assert monitor._is_uploaded(500) is False
        assert monitor._is_uploaded(1500) is True


# ---------------------------------------------------------------------------
# Jobs table layout builder
# ---------------------------------------------------------------------------


class TestBuildJobTable:
    """Tests for the build_job_table layout builder."""

    def test_empty_jobs_shows_placeholder(self):
        result = build_job_table([])
        assert result is not None

    def test_with_jobs_shows_table(self):
        jobs = [
            JobInfo(
                id=1001,
                name="test-math",
                status="success",
                duration=95.2,
                pipeline_id=500,
                pipeline_ref="main",
                pipeline_sha="abcdef12",
                web_url="https://example.com/-/jobs/1001",
                created_at="2025-01-01T00:00:00Z",
                finished_at="2025-01-01T00:01:35Z",
                artifacts_uploaded=True,
            ),
            JobInfo(
                id=1002,
                name="test-docker",
                status="failed",
                duration=210.5,
                pipeline_id=500,
                pipeline_ref="main",
                pipeline_sha="abcdef12",
                web_url="https://example.com/-/jobs/1002",
                created_at="2025-01-01T00:00:00Z",
                finished_at="2025-01-01T00:03:30Z",
                artifacts_uploaded=False,
            ),
        ]
        result = build_job_table(jobs)
        assert result is not None
