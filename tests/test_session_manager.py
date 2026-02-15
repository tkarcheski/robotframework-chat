"""Tests for dashboard.core.session_manager."""

import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from dashboard.core.session_manager import (
    RobotSession,
    SessionConfig,
    SessionLimitError,
    SessionManager,
    SessionStatus,
    _VALID_LOG_LEVELS,
)


# ---------------------------------------------------------------------------
# SessionConfig
# ---------------------------------------------------------------------------


class TestSessionConfig:
    @patch(
        "dashboard.core.session_manager.test_suites",
        return_value={"math": {"path": "robot/math/tests"}},
    )
    @patch("dashboard.core.session_manager.default_iq_levels", return_value=["100"])
    @patch("dashboard.core.session_manager.default_model", return_value="llama3")
    @patch("dashboard.core.session_manager.default_profile", return_value="STANDARD")
    def test_default_values(self, _prof, _model, _iq, _suites):
        cfg = SessionConfig()
        assert cfg.suite == "robot/math/tests"
        assert cfg.model == "llama3"
        assert cfg.log_level == "INFO"
        assert cfg.auto_recover is False
        assert cfg.dry_run is False

    def test_custom_values(self):
        cfg = SessionConfig(
            suite="robot/safety",
            iq_levels=["120"],
            model="mistral",
            profile="PERFORMANCE",
            ollama_host="gpu-server:11434",
            auto_recover=True,
            dry_run=True,
            randomize=True,
            log_level="DEBUG",
        )
        assert cfg.suite == "robot/safety"
        assert cfg.model == "mistral"
        assert cfg.auto_recover is True
        assert cfg.log_level == "DEBUG"

    def test_invalid_log_level(self):
        with pytest.raises(ValueError, match="log_level must be one of"):
            SessionConfig(
                suite="x",
                iq_levels=[],
                model="m",
                profile="p",
                log_level="VERBOSE",
            )

    def test_all_valid_log_levels_accepted(self):
        for level in _VALID_LOG_LEVELS:
            cfg = SessionConfig(
                suite="x", iq_levels=[], model="m", profile="p", log_level=level
            )
            assert cfg.log_level == level

    def test_empty_ollama_host_rejected(self):
        with pytest.raises(ValueError, match="ollama_host must be a non-empty string"):
            SessionConfig(
                suite="x",
                iq_levels=[],
                model="m",
                profile="p",
                ollama_host="",
            )


# ---------------------------------------------------------------------------
# RobotSession
# ---------------------------------------------------------------------------


class TestRobotSession:
    def _make_session(self, **kwargs):
        defaults = dict(
            session_id="abcd1234",
            config=SessionConfig(
                suite="x", iq_levels=[], model="m", profile="p"
            ),
        )
        defaults.update(kwargs)
        return RobotSession(**defaults)

    def test_runtime_idle(self):
        session = self._make_session()
        # Runtime should be a non-negative "Xm Ys" string
        assert "m" in session.runtime
        assert "s" in session.runtime

    def test_runtime_with_duration(self):
        start = datetime.now() - timedelta(minutes=2, seconds=30)
        session = self._make_session(start_time=start)
        runtime = session.runtime
        # Should be approximately "2m 30s"
        assert runtime.startswith("2m")

    def test_runtime_with_end_time(self):
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 5, 15)
        session = self._make_session(start_time=start, end_time=end)
        assert session.runtime == "5m 15s"

    def test_tab_color_idle(self):
        session = self._make_session(status=SessionStatus.IDLE)
        assert session.tab_color == "#C4B8A5"

    def test_tab_color_running(self):
        session = self._make_session(status=SessionStatus.RUNNING)
        assert session.tab_color == "#8C7E6A"

    def test_tab_color_failed(self):
        session = self._make_session(status=SessionStatus.FAILED)
        assert session.tab_color == "#C0392B"

    def test_tab_color_completed(self):
        session = self._make_session(status=SessionStatus.COMPLETED)
        assert session.tab_color == "#27AE60"

    def test_tab_color_recovering(self):
        session = self._make_session(status=SessionStatus.RECOVERING)
        assert session.tab_color == "#8C7E6A"

    def test_tab_label_format(self):
        session = self._make_session(session_id="abcd1234")
        label = session.tab_label
        assert "1234" in label  # last 4 chars of session_id
        assert "0m 0s" in label  # idle session shows 0m 0s

    def test_tab_label_running(self):
        session = self._make_session(status=SessionStatus.RUNNING)
        label = session.tab_label
        assert "⏳" in label

    def test_output_buffer_max_length(self):
        session = self._make_session()
        for i in range(1100):
            session.output_buffer.append(f"line {i}")
        assert len(session.output_buffer) == 1000


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class TestSessionManager:
    @patch(
        "dashboard.core.session_manager.test_suites",
        return_value={"math": {"path": "robot/math/tests"}},
    )
    @patch("dashboard.core.session_manager.default_iq_levels", return_value=["100"])
    @patch("dashboard.core.session_manager.default_model", return_value="llama3")
    @patch("dashboard.core.session_manager.default_profile", return_value="STANDARD")
    def _make_manager(self, _prof, _model, _iq, _suites):
        return SessionManager()

    def test_create_session_default_config(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        assert isinstance(session, RobotSession)
        assert session.status == SessionStatus.IDLE
        assert len(session.session_id) == 8

    def test_create_session_custom_config(self):
        mgr = self._make_manager()
        cfg = SessionConfig(
            suite="robot/safety", iq_levels=[], model="m", profile="p"
        )
        session = mgr.create_session(cfg)
        assert session.config.suite == "robot/safety"

    def test_create_session_invalid_config_type(self):
        mgr = self._make_manager()
        with pytest.raises(TypeError, match="config must be a SessionConfig"):
            mgr.create_session(config={"suite": "bad"})

    def test_create_session_limit(self):
        mgr = self._make_manager()
        for _ in range(5):
            mgr.create_session()
        with pytest.raises(SessionLimitError):
            mgr.create_session()

    def test_get_session_existing(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        found = mgr.get_session(session.session_id)
        assert found is session

    def test_get_session_nonexistent(self):
        mgr = self._make_manager()
        assert mgr.get_session("notexist") is None

    def test_get_session_invalid_type(self):
        mgr = self._make_manager()
        with pytest.raises(TypeError, match="session_id must be a str"):
            mgr.get_session(123)

    def test_get_session_empty_string(self):
        mgr = self._make_manager()
        with pytest.raises(ValueError, match="non-empty string"):
            mgr.get_session("")

    def test_list_sessions_empty(self):
        mgr = self._make_manager()
        assert mgr.list_sessions() == []

    def test_list_sessions_multiple(self):
        mgr = self._make_manager()
        mgr.create_session()
        mgr.create_session()
        assert len(mgr.list_sessions()) == 2

    def test_close_session_existing(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        assert mgr.close_session(session.session_id) is True
        assert mgr.get_session(session.session_id) is None

    def test_close_session_with_running_process(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        mock_process = MagicMock()
        session.process = mock_process
        mgr.close_session(session.session_id)
        mock_process.terminate.assert_called_once()

    def test_close_session_process_kill_on_timeout(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        mock_process = MagicMock()
        mock_process.wait.side_effect = Exception("timeout")
        session.process = mock_process
        mgr.close_session(session.session_id)
        mock_process.kill.assert_called_once()

    def test_close_session_nonexistent(self):
        mgr = self._make_manager()
        assert mgr.close_session("notexist") is False

    def test_close_session_invalid_type(self):
        mgr = self._make_manager()
        with pytest.raises(TypeError, match="session_id must be a str"):
            mgr.close_session(123)

    def test_update_session_status_to_running(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        mgr.update_session_status(session.session_id, SessionStatus.RUNNING)
        assert session.status == SessionStatus.RUNNING
        assert session.end_time is None

    def test_update_session_status_to_completed(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        mgr.update_session_status(session.session_id, SessionStatus.COMPLETED)
        assert session.status == SessionStatus.COMPLETED
        assert session.end_time is not None

    def test_update_session_status_to_failed(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        mgr.update_session_status(session.session_id, SessionStatus.FAILED)
        assert session.status == SessionStatus.FAILED
        assert session.end_time is not None

    def test_update_session_status_invalid_type(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        with pytest.raises(TypeError, match="status must be a SessionStatus"):
            mgr.update_session_status(session.session_id, "RUNNING")

    def test_update_session_status_nonexistent(self):
        mgr = self._make_manager()
        # Should not raise, just no-op
        mgr.update_session_status("notexist", SessionStatus.RUNNING)

    def test_add_output_line(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        mgr.add_output_line(session.session_id, "hello world")
        assert "hello world" in session.output_buffer

    def test_add_output_line_invalid_type(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        with pytest.raises(TypeError, match="line must be a str"):
            mgr.add_output_line(session.session_id, 123)

    def test_update_progress(self):
        mgr = self._make_manager()
        session = mgr.create_session()
        mgr.update_progress(session.session_id, 3, 10, "Test Math")
        assert session.progress == {"current": 3, "total": 10}
        assert session.current_test == "Test Math"

    def test_update_progress_negative_current(self):
        mgr = self._make_manager()
        with pytest.raises(ValueError, match="current must be >= 0"):
            mgr.update_progress("x", -1, 10)

    def test_update_progress_negative_total(self):
        mgr = self._make_manager()
        with pytest.raises(ValueError, match="total must be >= 0"):
            mgr.update_progress("x", 0, -5)

    def test_update_progress_current_exceeds_total(self):
        mgr = self._make_manager()
        with pytest.raises(ValueError, match="must not exceed total"):
            mgr.update_progress("x", 11, 10)

    def test_register_observer(self):
        mgr = self._make_manager()
        callback = MagicMock()
        mgr.register_observer(callback)
        assert callback in mgr._observers

    def test_register_observer_non_callable(self):
        mgr = self._make_manager()
        with pytest.raises(TypeError, match="callback must be callable"):
            mgr.register_observer("not_callable")

    def test_observer_called_on_status_change(self):
        mgr = self._make_manager()
        callback = MagicMock()
        mgr.register_observer(callback)
        session = mgr.create_session()
        mgr.update_session_status(session.session_id, SessionStatus.RUNNING)
        callback.assert_called_once_with(session.session_id)

    def test_observer_exception_swallowed(self):
        mgr = self._make_manager()
        bad_callback = MagicMock(side_effect=RuntimeError("boom"))
        mgr.register_observer(bad_callback)
        session = mgr.create_session()
        # Should not raise
        mgr.update_session_status(session.session_id, SessionStatus.RUNNING)

    def test_thread_safety_concurrent_creates(self):
        mgr = self._make_manager()
        results = []
        errors = []

        def create():
            try:
                s = mgr.create_session()
                results.append(s)
            except SessionLimitError:
                errors.append(True)

        threads = [threading.Thread(target=create) for _ in range(7)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# SessionLimitError
# ---------------------------------------------------------------------------


class TestSessionLimitError:
    def test_is_exception_subclass(self):
        assert issubclass(SessionLimitError, Exception)

    def test_message(self):
        err = SessionLimitError("max reached")
        assert str(err) == "max reached"
