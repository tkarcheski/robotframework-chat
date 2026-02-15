"""Tests for dashboard.core.robot_runner."""

from unittest.mock import MagicMock, patch

import pytest

from dashboard.core.session_manager import (
    RobotSession,
    SessionConfig,
    SessionStatus,
)
from dashboard.core.robot_runner import RobotRunner, RobotRunnerFactory


def _make_session(**overrides):
    defaults = dict(
        session_id="abcd1234",
        config=SessionConfig(
            suite="robot/math/tests",
            iq_levels=["100", "110"],
            model="llama3",
            profile="STANDARD",
        ),
    )
    defaults.update(overrides)
    return RobotSession(**defaults)


# ---------------------------------------------------------------------------
# RobotRunner
# ---------------------------------------------------------------------------


class TestRobotRunner:
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_init_creates_output_dir(self, mock_mkdir):
        session = _make_session()
        runner = RobotRunner(session, output_dir="/tmp/test_out")
        assert runner.session is session
        assert mock_mkdir.called

    def test_init_invalid_session_type(self):
        with pytest.raises(TypeError, match="session must be a RobotSession"):
            RobotRunner("not_a_session")

    def test_init_empty_output_dir(self):
        with pytest.raises(ValueError, match="output_dir must be a non-empty"):
            RobotRunner(_make_session(), output_dir="")

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_builds_correct_command(
        self, mock_mkdir, mock_popen, mock_sm
    ):
        session = _make_session()
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        cmd = mock_popen.call_args[0][0]
        assert cmd[:3] == ["uv", "run", "robot"]
        assert "-i" in cmd
        assert "IQ:100" in cmd
        assert "IQ:110" in cmd
        assert "-v" in cmd

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_includes_model_var(self, mock_mkdir, mock_popen, mock_sm):
        session = _make_session()
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        cmd = mock_popen.call_args[0][0]
        assert "MODEL:llama3" in cmd

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_dry_run(self, mock_mkdir, mock_popen, mock_sm):
        session = _make_session(
            config=SessionConfig(
                suite="robot/math",
                iq_levels=[],
                model="m",
                profile="p",
                dry_run=True,
            )
        )
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        cmd = mock_popen.call_args[0][0]
        assert "--dryrun" in cmd

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_randomize(self, mock_mkdir, mock_popen, mock_sm):
        session = _make_session(
            config=SessionConfig(
                suite="robot/math",
                iq_levels=[],
                model="m",
                profile="p",
                randomize=True,
            )
        )
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        cmd = mock_popen.call_args[0][0]
        assert "--randomize" in cmd
        assert "all" in cmd

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_custom_log_level(self, mock_mkdir, mock_popen, mock_sm):
        session = _make_session(
            config=SessionConfig(
                suite="robot/math",
                iq_levels=[],
                model="m",
                profile="p",
                log_level="DEBUG",
            )
        )
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        cmd = mock_popen.call_args[0][0]
        assert "-L" in cmd
        idx = cmd.index("-L")
        assert cmd[idx + 1] == "DEBUG"

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_success_sets_completed(
        self, mock_mkdir, mock_popen, mock_sm
    ):
        session = _make_session()
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        mock_sm.update_session_status.assert_any_call(
            session.session_id, SessionStatus.COMPLETED
        )

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_failure_sets_failed(self, mock_mkdir, mock_popen, mock_sm):
        session = _make_session()
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 1
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        mock_sm.update_session_status.assert_any_call(
            session.session_id, SessionStatus.FAILED
        )

    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_stop_sets_event(self, mock_mkdir):
        session = _make_session()
        runner = RobotRunner(session)
        runner.stop()
        assert runner._stop_event.is_set()

    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_stop_terminates_process(self, mock_mkdir):
        session = _make_session()
        mock_process = MagicMock()
        session.process = mock_process
        runner = RobotRunner(session)
        runner.stop()
        mock_process.terminate.assert_called_once()

    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_stop_kills_on_timeout(self, mock_mkdir):
        session = _make_session()
        mock_process = MagicMock()
        mock_process.wait.side_effect = Exception("timeout")
        session.process = mock_process
        runner = RobotRunner(session)
        runner.stop()
        mock_process.kill.assert_called_once()

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_parse_progress_pass(self, mock_mkdir, mock_sm):
        session = _make_session()
        runner = RobotRunner(session)
        runner._parse_progress("Test Addition | PASS |")
        mock_sm.update_progress.assert_called_once()
        call_kwargs = mock_sm.update_progress.call_args
        assert call_kwargs[1]["current_test"] == "Test Addition"

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_parse_progress_fail(self, mock_mkdir, mock_sm):
        session = _make_session()
        runner = RobotRunner(session)
        runner._parse_progress("Test Division | FAIL |")
        mock_sm.update_progress.assert_called_once()

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_parse_progress_no_match(self, mock_mkdir, mock_sm):
        session = _make_session()
        runner = RobotRunner(session)
        runner._parse_progress("some random log output")
        mock_sm.update_progress.assert_not_called()

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_ollama_endpoint_var(self, mock_mkdir, mock_popen, mock_sm):
        session = _make_session(
            config=SessionConfig(
                suite="robot/math",
                iq_levels=[],
                model="m",
                profile="p",
                ollama_host="gpu-server:11434",
            )
        )
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        cmd = mock_popen.call_args[0][0]
        assert "OLLAMA_ENDPOINT:http://gpu-server:11434" in cmd

    @patch("dashboard.core.robot_runner.session_manager")
    @patch("dashboard.core.robot_runner.subprocess.Popen")
    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_execute_robot_includes_timestamp_flag(
        self, mock_mkdir, mock_popen, mock_sm
    ):
        session = _make_session()
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        runner = RobotRunner(session)
        runner._execute_robot()

        cmd = mock_popen.call_args[0][0]
        assert "-T" in cmd


# ---------------------------------------------------------------------------
# RobotRunnerFactory
# ---------------------------------------------------------------------------


class TestRobotRunnerFactory:
    def setup_method(self):
        RobotRunnerFactory._runners = {}

    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_create_runner_returns_runner(self, mock_mkdir):
        session = _make_session()
        runner = RobotRunnerFactory.create_runner(session)
        assert isinstance(runner, RobotRunner)

    def test_create_runner_invalid_session(self):
        with pytest.raises(TypeError, match="session must be a RobotSession"):
            RobotRunnerFactory.create_runner("not_a_session")

    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_get_runner_existing(self, mock_mkdir):
        session = _make_session()
        runner = RobotRunnerFactory.create_runner(session)
        found = RobotRunnerFactory.get_runner(session.session_id)
        assert found is runner

    def test_get_runner_nonexistent(self):
        assert RobotRunnerFactory.get_runner("notexist") is None

    def test_get_runner_invalid_type(self):
        with pytest.raises(TypeError, match="session_id must be a str"):
            RobotRunnerFactory.get_runner(123)

    @patch("dashboard.core.robot_runner.Path.mkdir")
    def test_stop_runner_existing(self, mock_mkdir):
        session = _make_session()
        RobotRunnerFactory.create_runner(session)
        result = RobotRunnerFactory.stop_runner(session.session_id)
        assert result is True
        assert RobotRunnerFactory.get_runner(session.session_id) is None

    def test_stop_runner_nonexistent(self):
        assert RobotRunnerFactory.stop_runner("notexist") is False

    def test_stop_runner_invalid_type(self):
        with pytest.raises(TypeError, match="session_id must be a str"):
            RobotRunnerFactory.stop_runner(123)
