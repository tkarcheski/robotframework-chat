"""Tests for dashboard monitoring module (Ollama + GitLab)."""

import os
from unittest.mock import MagicMock, patch

from dashboard.monitoring import (
    OllamaMonitor,
    PipelineInfo,
    PipelineMonitor,
    _detect_gitlab_from_git_remote,
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
    def test_not_configured_when_empty(self, mock_detect):
        mock_detect.return_value = ("", "")
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
