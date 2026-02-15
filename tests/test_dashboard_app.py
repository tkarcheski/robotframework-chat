"""Tests for dashboard.app callback functions."""

from unittest.mock import MagicMock, patch

import dash_bootstrap_components as dbc
import pytest
from dash.exceptions import PreventUpdate

from dashboard.core.session_manager import SessionStatus


# ---------------------------------------------------------------------------
# _toast helper
# ---------------------------------------------------------------------------


class TestToast:
    def test_returns_dbc_toast(self):
        from dashboard.app import _toast

        result = _toast("hello", "Header", "success")
        assert isinstance(result, dbc.Toast)

    def test_toast_content(self):
        from dashboard.app import _toast

        result = _toast("test msg", "MyHeader", "danger")
        assert result.children == "test msg"


# ---------------------------------------------------------------------------
# update_live_output
# ---------------------------------------------------------------------------


class TestUpdateLiveOutput:
    @patch("dashboard.app.session_manager")
    def test_returns_correct_lengths(self, mock_sm):
        from dashboard.app import update_live_output

        session = MagicMock()
        session.output_buffer = ["line1", "line2"]
        session.progress = {"current": 3, "total": 10}
        session.status = SessionStatus.RUNNING
        session.current_test = "Test Math"
        mock_sm.list_sessions.return_value = [session]

        panel_ids = [{"type": "console-output", "index": 0}]
        texts, values, labels, tests = update_live_output(1, panel_ids)

        assert len(texts) == 1
        assert len(values) == 1
        assert values[0] == 30  # 3/10 = 30%
        assert "Test Math" in tests[0]

    @patch("dashboard.app.session_manager")
    def test_deleted_session_panel(self, mock_sm):
        from dashboard.app import update_live_output

        mock_sm.list_sessions.return_value = []
        panel_ids = [{"type": "console-output", "index": 0}]
        texts, values, labels, tests = update_live_output(1, panel_ids)

        assert texts[0] == ""
        assert values[0] == 0
        assert "deleted" in tests[0].lower()

    @patch("dashboard.app.session_manager")
    def test_idle_session_shows_idle_label(self, mock_sm):
        from dashboard.app import update_live_output

        session = MagicMock()
        session.output_buffer = []
        session.progress = {}
        session.status = SessionStatus.IDLE
        session.current_test = ""
        mock_sm.list_sessions.return_value = [session]

        panel_ids = [{"type": "console-output", "index": 0}]
        _, _, labels, _ = update_live_output(1, panel_ids)
        assert labels[0] == "Idle"


# ---------------------------------------------------------------------------
# update_ui_states
# ---------------------------------------------------------------------------


class TestUpdateUiStates:
    @patch("dashboard.app.session_manager")
    def test_running_session_disables_controls(self, mock_sm):
        from dashboard.app import update_ui_states

        session = MagicMock()
        session.status = SessionStatus.RUNNING
        mock_sm.list_sessions.return_value = [session]

        btn_ids = [{"type": "run-btn", "index": 0}]
        result = update_ui_states(1, btn_ids)

        run_d, stop_d, replay_d, _ = result[0], result[1], result[2], result[3]
        assert run_d[0] is True  # Run disabled
        assert stop_d[0] is False  # Stop enabled
        assert replay_d[0] is True  # Replay disabled

    @patch("dashboard.app.session_manager")
    def test_idle_session_enables_controls(self, mock_sm):
        from dashboard.app import update_ui_states

        session = MagicMock()
        session.status = SessionStatus.IDLE
        mock_sm.list_sessions.return_value = [session]

        btn_ids = [{"type": "run-btn", "index": 0}]
        result = update_ui_states(1, btn_ids)

        run_d, stop_d = result[0], result[1]
        assert run_d[0] is False  # Run enabled
        assert stop_d[0] is True  # Stop disabled

    @patch("dashboard.app.session_manager")
    def test_completed_session_enables_upload(self, mock_sm):
        from dashboard.app import update_ui_states

        session = MagicMock()
        session.status = SessionStatus.COMPLETED
        mock_sm.list_sessions.return_value = [session]

        btn_ids = [{"type": "run-btn", "index": 0}]
        result = update_ui_states(1, btn_ids)

        upload_d = result[3]
        assert upload_d[0] is False  # Upload enabled


# ---------------------------------------------------------------------------
# update_tab_styles
# ---------------------------------------------------------------------------


class TestUpdateTabStyles:
    @patch("dashboard.app.session_manager")
    def test_tab_count_matches_sessions(self, mock_sm):
        from dashboard.app import update_tab_styles

        s1 = MagicMock()
        s1.tab_label = "Session 1"
        s1.tab_color = "#27AE60"
        s2 = MagicMock()
        s2.tab_label = "Session 2"
        s2.tab_color = "#C0392B"
        mock_sm.list_sessions.return_value = [s1, s2]

        tabs = update_tab_styles(1)
        assert len(tabs) == 2


# ---------------------------------------------------------------------------
# toggle_tab_visibility
# ---------------------------------------------------------------------------


class TestToggleTabVisibility:
    def test_active_tab_visible(self):
        from dashboard.app import toggle_tab_visibility

        panel_ids = [
            {"type": "session-panel", "index": 0},
            {"type": "session-panel", "index": 1},
        ]
        styles = toggle_tab_visibility("tab-0", panel_ids)
        assert styles[0]["display"] == "block"
        assert styles[1]["display"] == "none"

    def test_no_active_tab_prevents_update(self):
        from dashboard.app import toggle_tab_visibility

        with pytest.raises(PreventUpdate):
            toggle_tab_visibility(None, [])


# ---------------------------------------------------------------------------
# switch_top_tab
# ---------------------------------------------------------------------------


class TestSwitchTopTab:
    def test_sessions_tab_active(self):
        from dashboard.app import switch_top_tab

        sessions, ollama, pipelines = switch_top_tab("top-sessions")
        assert sessions["display"] == "block"
        assert ollama["display"] == "none"
        assert pipelines["display"] == "none"

    def test_ollama_tab_active(self):
        from dashboard.app import switch_top_tab

        sessions, ollama, pipelines = switch_top_tab("top-ollama")
        assert sessions["display"] == "none"
        assert ollama["display"] == "block"

    def test_pipelines_tab_active(self):
        from dashboard.app import switch_top_tab

        sessions, ollama, pipelines = switch_top_tab("top-pipelines")
        assert pipelines["display"] == "block"
