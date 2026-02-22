"""Tests for dashboard/monitoring.py — monitoring helpers and layout builders."""

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


from dashboard.monitoring import (
    JobInfo,
    OllamaMonitor,
    PipelineInfo,
    PipelineMonitor,
    _format_duration,
    _short_ts,
    build_job_table,
    build_pipeline_table,
)


# ---------------------------------------------------------------------------
# _short_ts
# ---------------------------------------------------------------------------


class TestShortTs:
    def test_valid_iso(self):
        assert _short_ts("2024-06-15T14:30:00Z") == "14:30"

    def test_valid_iso_no_z(self):
        result = _short_ts("2024-06-15T09:05:00")
        assert "09:05" in result

    def test_empty_string(self):
        assert _short_ts("") == ""

    def test_invalid_format(self):
        result = _short_ts("not-a-date")
        assert result == "not-a-date"[:16]

    def test_with_timezone_offset(self):
        result = _short_ts("2024-01-01T23:59:00+00:00")
        assert "23:59" in result


# ---------------------------------------------------------------------------
# _format_duration
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_none(self):
        assert _format_duration(None) == "-"

    def test_zero(self):
        assert _format_duration(0) == "0s"

    def test_seconds_only(self):
        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2m 5s"

    def test_hours_minutes_seconds(self):
        assert _format_duration(3661) == "1h 1m 1s"

    def test_exact_hours(self):
        assert _format_duration(7200) == "2h"

    def test_exact_minutes(self):
        assert _format_duration(120) == "2m"

    def test_float_seconds(self):
        # Should truncate to int
        assert _format_duration(90.7) == "1m 30s"


# ---------------------------------------------------------------------------
# _detect_gitlab_from_git_remote
# ---------------------------------------------------------------------------


class TestDetectGitlabFromGitRemote:
    @patch("dashboard.monitoring.subprocess.run")
    def test_ssh_remote(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="git@gitlab.example.com:group/project.git\n"
        )
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == "https://gitlab.example.com"
        assert path == "group/project"

    @patch("dashboard.monitoring.subprocess.run")
    def test_https_remote(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://gitlab.example.com/team/repo.git\n"
        )
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == "https://gitlab.example.com"
        assert path == "team/repo"

    @patch("dashboard.monitoring.subprocess.run")
    def test_https_no_dot_git(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://gitlab.example.com/team/repo\n"
        )
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == "https://gitlab.example.com"
        assert path == "team/repo"

    @patch("dashboard.monitoring.subprocess.run")
    def test_localhost_skipped(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://127.0.0.1/group/repo.git\n"
        )
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == ""
        assert path == ""

    @patch("dashboard.monitoring.subprocess.run")
    def test_git_command_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        assert _detect_gitlab_from_git_remote() == ("", "")

    @patch("dashboard.monitoring.subprocess.run")
    def test_exception_returns_empty(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        assert _detect_gitlab_from_git_remote() == ("", "")

    @patch("dashboard.monitoring.subprocess.run")
    def test_https_with_git_prefix(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://gitlab.example.com/git/group/repo.git\n"
        )
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        api_url, path = _detect_gitlab_from_git_remote()
        assert api_url == "https://gitlab.example.com"
        assert path == "group/repo"

    @patch("dashboard.monitoring.subprocess.run")
    def test_unrecognised_remote(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="svn://example.com/repo\n"
        )
        from dashboard.monitoring import _detect_gitlab_from_git_remote

        assert _detect_gitlab_from_git_remote() == ("", "")


# ---------------------------------------------------------------------------
# _monitoring_config
# ---------------------------------------------------------------------------


class TestMonitoringConfig:
    @patch("dashboard.monitoring.load_config", return_value={})
    def test_defaults_when_empty(self, _):
        from dashboard.monitoring import _monitoring_config

        cfg = _monitoring_config()
        assert cfg["poll_interval_seconds"] == 30
        assert cfg["history_hours"] == 24
        assert cfg["pipeline_count"] == 20

    @patch(
        "dashboard.monitoring.load_config",
        return_value={"monitoring": {"poll_interval_seconds": 60}},
    )
    def test_user_overrides(self, _):
        from dashboard.monitoring import _monitoring_config

        cfg = _monitoring_config()
        assert cfg["poll_interval_seconds"] == 60
        # Other defaults still present
        assert cfg["history_hours"] == 24


# ---------------------------------------------------------------------------
# _node_list
# ---------------------------------------------------------------------------


class TestNodeList:
    @patch("dashboard.monitoring.docker_aware_nodes", side_effect=lambda x: x)
    @patch(
        "dashboard.monitoring.load_config",
        return_value={"nodes": [{"hostname": "host1", "port": 11434}]},
    )
    @patch.dict("os.environ", {"OLLAMA_NODES_LIST": ""})
    def test_from_config(self, _cfg, _docker):
        from dashboard.monitoring import _node_list

        nodes = _node_list()
        assert len(nodes) == 1
        assert nodes[0]["hostname"] == "host1"

    @patch("dashboard.monitoring.docker_aware_nodes", side_effect=lambda x: x)
    @patch("dashboard.monitoring.load_config", return_value={})
    @patch.dict("os.environ", {"OLLAMA_NODES_LIST": "nodeA,nodeB"})
    def test_from_env_var(self, _cfg, _docker):
        from dashboard.monitoring import _node_list

        nodes = _node_list()
        assert len(nodes) == 2
        assert nodes[0]["hostname"] == "nodeA"
        assert nodes[1]["hostname"] == "nodeB"
        assert all(n["port"] == 11434 for n in nodes)

    @patch("dashboard.monitoring.docker_aware_nodes", side_effect=lambda x: x)
    @patch("dashboard.monitoring.load_config", return_value={})
    @patch.dict("os.environ", {"OLLAMA_NODES_LIST": ""})
    def test_empty_env(self, _cfg, _docker):
        from dashboard.monitoring import _node_list

        nodes = _node_list()
        assert nodes == []


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_pipeline_info(self):
        p = PipelineInfo(
            id=1,
            status="success",
            ref="main",
            sha="abc12345",
            created_at="2024-01-01",
            updated_at="2024-01-02",
            web_url="https://x",
        )
        assert p.id == 1
        assert p.source == ""  # default

    def test_job_info(self):
        j = JobInfo(
            id=10,
            name="test",
            status="success",
            duration=120.0,
            pipeline_id=1,
            pipeline_ref="main",
            pipeline_sha="abc",
            web_url="https://x",
            created_at="2024-01-01",
            finished_at="2024-01-02",
        )
        assert j.artifacts_uploaded is False  # default

    def test_ollama_snapshot(self):
        from dashboard.monitoring import _OllamaSnapshot

        snap = _OllamaSnapshot(ts=datetime.now(), reachable=True)
        assert snap.running_models == []
        assert snap.error == ""


# ---------------------------------------------------------------------------
# PipelineMonitor._is_uploaded
# ---------------------------------------------------------------------------


class TestPipelineMonitorIsUploaded:
    def test_match(self):
        monitor = MagicMock(spec=PipelineMonitor)
        monitor._uploaded_pipeline_urls = {"https://gitlab.example.com/pipelines/42"}
        assert PipelineMonitor._is_uploaded(monitor, 42) is True

    def test_no_match(self):
        monitor = MagicMock(spec=PipelineMonitor)
        monitor._uploaded_pipeline_urls = {"https://gitlab.example.com/pipelines/99"}
        assert PipelineMonitor._is_uploaded(monitor, 42) is False

    def test_empty(self):
        monitor = MagicMock(spec=PipelineMonitor)
        monitor._uploaded_pipeline_urls = set()
        assert PipelineMonitor._is_uploaded(monitor, 1) is False


# ---------------------------------------------------------------------------
# PipelineMonitor._resolve_gitlab_settings
# ---------------------------------------------------------------------------


class TestResolveGitlabSettings:
    @patch.dict(
        "os.environ",
        {
            "CI_API_V4_URL": "https://gitlab.example.com/api/v4",
            "CI_PROJECT_ID": "42",
        },
    )
    def test_ci_env_vars(self):
        monitor = MagicMock(spec=PipelineMonitor)
        cfg = {}
        url, pid = PipelineMonitor._resolve_gitlab_settings(monitor, cfg)
        assert url == "https://gitlab.example.com"
        assert pid == "42"

    @patch.dict(
        "os.environ",
        {"GITLAB_API_URL": "https://gitlab.co", "GITLAB_PROJECT_ID": "77"},
        clear=False,
    )
    @patch.dict(
        "os.environ",
        {"CI_API_V4_URL": "", "CI_PROJECT_ID": ""},
        clear=False,
    )
    def test_explicit_env_vars(self):
        monitor = MagicMock(spec=PipelineMonitor)
        cfg = {"gitlab_api_url": "", "gitlab_project_id": ""}
        url, pid = PipelineMonitor._resolve_gitlab_settings(monitor, cfg)
        assert url == "https://gitlab.co"
        assert pid == "77"

    @patch.dict(
        "os.environ",
        {
            "CI_API_V4_URL": "",
            "CI_PROJECT_ID": "",
            "GITLAB_API_URL": "",
            "GITLAB_PROJECT_ID": "",
        },
        clear=False,
    )
    @patch("dashboard.monitoring._detect_gitlab_from_git_remote", return_value=("", ""))
    def test_no_config(self, _):
        monitor = MagicMock(spec=PipelineMonitor)
        cfg = {"gitlab_api_url": "", "gitlab_project_id": ""}
        url, pid = PipelineMonitor._resolve_gitlab_settings(monitor, cfg)
        assert url == ""
        assert pid == ""


# ---------------------------------------------------------------------------
# OllamaMonitor data access
# ---------------------------------------------------------------------------


class TestOllamaMonitorDataAccess:
    def _make_monitor(self):
        """Create an OllamaMonitor without triggering __init__ side effects."""
        from dashboard.monitoring import _OllamaSnapshot

        monitor = object.__new__(OllamaMonitor)
        monitor._nodes = [
            {"hostname": "host1", "port": 11434},
            {"hostname": "host2", "port": 11434},
        ]
        monitor._history = {
            "host1": deque(
                [_OllamaSnapshot(ts=datetime.now(), reachable=True)], maxlen=100
            ),
            "host2": deque(maxlen=100),
        }
        monitor._poll_interval = 30
        return monitor

    def test_node_names(self):
        m = self._make_monitor()
        assert m.node_names() == ["host1", "host2"]

    def test_latest_with_data(self):
        m = self._make_monitor()
        snap = m.latest("host1")
        assert snap is not None
        assert snap.reachable is True

    def test_latest_no_data(self):
        m = self._make_monitor()
        assert m.latest("host2") is None

    def test_latest_unknown_host(self):
        m = self._make_monitor()
        assert m.latest("unknown") is None

    def test_history(self):
        m = self._make_monitor()
        assert len(m.history("host1")) == 1
        assert m.history("host2") == []
        assert m.history("unknown") == []


# ---------------------------------------------------------------------------
# build_pipeline_table
# ---------------------------------------------------------------------------


class TestBuildPipelineTable:
    def test_empty_no_monitor(self):
        div = build_pipeline_table([])
        # Should show "Not Configured" message
        _assert_contains_text(div, "Not Configured")

    def test_empty_with_error(self):
        monitor = MagicMock(spec=PipelineMonitor)
        monitor.is_configured = True
        monitor.fetch_error = "Connection refused"
        div = build_pipeline_table([], monitor=monitor)
        _assert_contains_text(div, "Connection refused")

    def test_with_pipelines(self):
        pipelines = [
            PipelineInfo(
                id=1,
                status="success",
                ref="main",
                sha="abcdef12",
                created_at="2024-01-01T12:00:00Z",
                updated_at="2024-01-01T13:00:00Z",
                web_url="https://example.com/pipelines/1",
                source="push",
            )
        ]
        div = build_pipeline_table(pipelines)
        text = _extract_text(div)
        assert "success" in text
        assert "main" in text
        assert "abcdef12" in text


# ---------------------------------------------------------------------------
# build_job_table
# ---------------------------------------------------------------------------


class TestBuildJobTable:
    def test_empty_no_monitor(self):
        div = build_job_table([])
        _assert_contains_text(div, "No jobs found")

    def test_empty_with_error(self):
        monitor = MagicMock(spec=PipelineMonitor)
        monitor.fetch_error = "Auth failed"
        div = build_job_table([], monitor=monitor)
        _assert_contains_text(div, "Auth failed")

    def test_with_jobs(self):
        jobs = [
            JobInfo(
                id=10,
                name="test-suite",
                status="success",
                duration=90.5,
                pipeline_id=1,
                pipeline_ref="main",
                pipeline_sha="abc12345",
                web_url="https://example.com/jobs/10",
                created_at="2024-01-01T12:00:00Z",
                finished_at="2024-01-01T12:05:00Z",
                artifacts_uploaded=True,
            ),
            JobInfo(
                id=11,
                name="lint",
                status="failed",
                duration=None,
                pipeline_id=1,
                pipeline_ref="main",
                pipeline_sha="abc12345",
                web_url="",
                created_at="2024-01-01T12:00:00Z",
                finished_at="",
            ),
        ]
        div = build_job_table(jobs)
        text = _extract_text(div)
        assert "test-suite" in text
        assert "lint" in text
        assert "Uploaded" in text


# ---------------------------------------------------------------------------
# build_ollama_cards
# ---------------------------------------------------------------------------


class TestBuildOllamaCards:
    def test_no_nodes(self):
        monitor = MagicMock(spec=OllamaMonitor)
        monitor.node_names.return_value = []
        cards = build_pipeline_table([])  # just to verify it doesn't crash
        assert cards is not None

    def test_with_offline_node(self):
        from dashboard.monitoring import _OllamaSnapshot, build_ollama_cards

        monitor = object.__new__(OllamaMonitor)
        monitor._nodes = [{"hostname": "host1", "port": 11434}]
        snap = _OllamaSnapshot(
            ts=datetime.now(), reachable=False, error="Connection refused"
        )
        monitor._history = {"host1": deque([snap], maxlen=100)}
        monitor._poll_interval = 30

        cards = build_ollama_cards(monitor)
        assert len(cards) == 1

    def test_with_busy_node(self):
        from dashboard.monitoring import _OllamaSnapshot, build_ollama_cards

        monitor = object.__new__(OllamaMonitor)
        monitor._nodes = [{"hostname": "host1", "port": 11434}]
        snap = _OllamaSnapshot(
            ts=datetime.now(),
            reachable=True,
            running_models=[{"name": "llama3"}],
        )
        monitor._history = {"host1": deque([snap], maxlen=100)}
        monitor._poll_interval = 30

        cards = build_ollama_cards(monitor)
        assert len(cards) == 1

    def test_with_idle_node(self):
        from dashboard.monitoring import _OllamaSnapshot, build_ollama_cards

        monitor = object.__new__(OllamaMonitor)
        monitor._nodes = [{"hostname": "host1", "port": 11434}]
        snap = _OllamaSnapshot(ts=datetime.now(), reachable=True)
        monitor._history = {"host1": deque([snap], maxlen=100)}
        monitor._poll_interval = 30

        cards = build_ollama_cards(monitor)
        assert len(cards) == 1

    def test_with_no_snapshot(self):
        from dashboard.monitoring import build_ollama_cards

        monitor = object.__new__(OllamaMonitor)
        monitor._nodes = [{"hostname": "host1", "port": 11434}]
        monitor._history = {"host1": deque(maxlen=100)}
        monitor._poll_interval = 30

        cards = build_ollama_cards(monitor)
        assert len(cards) == 1


# ---------------------------------------------------------------------------
# _build_timeline_fig
# ---------------------------------------------------------------------------


class TestBuildTimelineFig:
    def test_empty_history(self):
        from dashboard.monitoring import _build_timeline_fig

        monitor = object.__new__(OllamaMonitor)
        monitor._nodes = [{"hostname": "host1", "port": 11434}]
        monitor._history = {"host1": deque(maxlen=100)}
        monitor._poll_interval = 30

        fig = _build_timeline_fig(monitor, "host1")
        assert fig is not None

    def test_with_history(self):
        from dashboard.monitoring import _OllamaSnapshot, _build_timeline_fig

        monitor = object.__new__(OllamaMonitor)
        monitor._poll_interval = 30
        now = datetime.now()
        snaps = [
            _OllamaSnapshot(ts=now - timedelta(hours=1), reachable=True),
            _OllamaSnapshot(
                ts=now - timedelta(minutes=30),
                reachable=True,
                running_models=[{"name": "llama3"}],
            ),
            _OllamaSnapshot(
                ts=now - timedelta(minutes=5),
                reachable=False,
                error="timeout",
            ),
        ]
        monitor._history = {"host1": deque(snaps, maxlen=100)}

        fig = _build_timeline_fig(monitor, "host1")
        assert fig is not None
        # Should have one trace (Bar)
        assert len(fig.data) == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text(component) -> str:
    """Recursively extract text from a Dash component tree."""
    parts = []
    if isinstance(component, str):
        return component
    if hasattr(component, "children"):
        children = component.children
        if isinstance(children, str):
            parts.append(children)
        elif isinstance(children, list):
            for child in children:
                parts.append(_extract_text(child))
        elif children is not None:
            parts.append(_extract_text(children))
    return " ".join(parts)


def _assert_contains_text(component, text: str) -> None:
    """Assert that a Dash component tree contains the given text."""
    extracted = _extract_text(component)
    assert text in extracted, f"Expected '{text}' in component text: {extracted[:200]}"
