"""Dash callbacks for Robot Framework Dashboard."""

import json
from dash import Input, Output, State, callback_context
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from dashboard.core.robot_runner import RobotRunnerFactory
from dashboard.core.session_manager import (
    SessionConfig,
    SessionStatus,
    session_manager,
)


def register_callbacks(app):
    """Register all callbacks with the Dash app."""

    @app.callback(
        Output({"type": "console-output", "session": "ALL"}, "children"),
        Output({"type": "progress-bar", "session": "ALL"}, "value"),
        Output({"type": "progress-bar", "session": "ALL"}, "label"),
        Output({"type": "current-test", "session": "ALL"}, "children"),
        Input("interval-component", "n_intervals"),
        State("active-session", "data"),
    )
    def update_live_output(n_intervals, active_session_id):
        """Update console output and progress for all sessions."""
        sessions = session_manager.list_sessions()

        outputs = []
        progress_values = []
        progress_labels = []
        current_tests = []

        for session in sessions:
            # Console output
            output_text = "\n".join(session.output_buffer)
            outputs.append(output_text)

            # Progress
            if session.progress:
                current = session.progress.get("current", 0)
                total = session.progress.get("total", 1)
                percentage = min(100, int((current / total) * 100))
            else:
                current, total, percentage = 0, 0, 0

            progress_values.append(percentage)
            progress_labels.append(f"{percentage}% ({current}/{total})")

            # Current test
            status_text = f"Status: {session.status.value}"
            if session.current_test:
                status_text += f" | Current: {session.current_test}"
            current_tests.append(status_text)

        return outputs, progress_values, progress_labels, current_tests

    @app.callback(
        Output("toast-container", "children", allow_duplicate=True),
        Input({"type": "run-btn", "session": "ALL"}, "n_clicks"),
        State({"type": "suite-dropdown", "session": "ALL"}, "value"),
        State({"type": "iq-dropdown", "session": "ALL"}, "value"),
        State({"type": "model-dropdown", "session": "ALL"}, "value"),
        State({"type": "profile-dropdown", "session": "ALL"}, "value"),
        State({"type": "auto-recover-check", "session": "ALL"}, "value"),
        State({"type": "dry-run-check", "session": "ALL"}, "value"),
        prevent_initial_call=True,
    )
    def handle_run_button(
        n_clicks_list,
        suite_values,
        iq_values,
        model_values,
        profile_values,
        auto_recover_values,
        dry_run_values,
    ):
        """Handle run button click."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        # Find which button was clicked
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        button_data = json.loads(button_id)
        session_id = button_data.get("session")

        if not session_id:
            raise PreventUpdate

        session = session_manager.get_session(session_id)
        if not session:
            return dbc.Toast(
                "Session not found",
                id="run-error",
                header="Error",
                is_open=True,
                color="danger",
            )

        if session.status == SessionStatus.RUNNING:
            return dbc.Toast(
                "Session is already running",
                id="run-warning",
                header="Warning",
                is_open=True,
                color="warning",
            )

        # Find the index of this session in the list of all sessions
        sessions = session_manager.list_sessions()
        session_ids = [s.session_id for s in sessions]
        try:
            idx = session_ids.index(session_id)
        except ValueError:
            idx = 0

        # Update config from UI using the correct index
        config = SessionConfig(
            suite=suite_values[idx]
            if suite_values and idx < len(suite_values)
            else session.config.suite,
            iq_levels=iq_values[idx]
            if iq_values and idx < len(iq_values)
            else session.config.iq_levels,
            model=model_values[idx]
            if model_values and idx < len(model_values)
            else session.config.model,
            profile=profile_values[idx]
            if profile_values and idx < len(profile_values)
            else session.config.profile,
            auto_recover=bool(
                auto_recover_values
                and idx < len(auto_recover_values)
                and auto_recover_values[idx]
                and True in auto_recover_values[idx]
            ),
            dry_run=bool(
                dry_run_values
                and idx < len(dry_run_values)
                and dry_run_values[idx]
                and True in dry_run_values[idx]
            ),
        )
        session.config = config

        # Create and start runner
        runner = RobotRunnerFactory.create_runner(session)
        runner.start()

        return dbc.Toast(
            f"Started test run for Session {session_id[-4:]}",
            id="run-success",
            header="Started",
            is_open=True,
            color="success",
        )

    @app.callback(
        Output("toast-container", "children", allow_duplicate=True),
        Input({"type": "stop-btn", "session": "ALL"}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_stop_button(n_clicks_list):
        """Handle stop button click."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        button_data = json.loads(button_id)
        session_id = button_data.get("session")

        if not session_id:
            raise PreventUpdate

        success = RobotRunnerFactory.stop_runner(session_id)

        if success:
            return dbc.Toast(
                f"Stopped Session {session_id[-4:]}",
                id="stop-success",
                header="Stopped",
                is_open=True,
                color="info",
            )
        else:
            return dbc.Toast(
                "Failed to stop session",
                id="stop-error",
                header="Error",
                is_open=True,
                color="danger",
            )

    @app.callback(
        Output("toast-container", "children", allow_duplicate=True),
        Input({"type": "save-btn", "session": "ALL"}, "n_clicks"),
        State({"type": "suite-dropdown", "session": "ALL"}, "value"),
        State({"type": "iq-dropdown", "session": "ALL"}, "value"),
        State({"type": "model-dropdown", "session": "ALL"}, "value"),
        State({"type": "profile-dropdown", "session": "ALL"}, "value"),
        State({"type": "auto-recover-check", "session": "ALL"}, "value"),
        State({"type": "dry-run-check", "session": "ALL"}, "value"),
        prevent_initial_call=True,
    )
    def handle_save_button(
        n_clicks_list,
        suite_values,
        iq_values,
        model_values,
        profile_values,
        auto_recover_values,
        dry_run_values,
    ):
        """Handle save button click - saves current form values to session config."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        button_data = json.loads(button_id)
        session_id = button_data.get("session")

        if not session_id:
            raise PreventUpdate

        session = session_manager.get_session(session_id)
        if not session:
            return dbc.Toast(
                "Session not found",
                id="save-error",
                header="Error",
                is_open=True,
                color="danger",
            )

        # Find the index of this session in the list
        sessions = session_manager.list_sessions()
        session_ids = [s.session_id for s in sessions]
        try:
            idx = session_ids.index(session_id)
        except ValueError:
            idx = 0

        # Save config from UI using the correct index
        config = SessionConfig(
            suite=suite_values[idx]
            if suite_values and idx < len(suite_values)
            else session.config.suite,
            iq_levels=iq_values[idx]
            if iq_values and idx < len(iq_values)
            else session.config.iq_levels,
            model=model_values[idx]
            if model_values and idx < len(model_values)
            else session.config.model,
            profile=profile_values[idx]
            if profile_values and idx < len(profile_values)
            else session.config.profile,
            auto_recover=bool(
                auto_recover_values
                and idx < len(auto_recover_values)
                and auto_recover_values[idx]
                and True in auto_recover_values[idx]
            ),
            dry_run=bool(
                dry_run_values
                and idx < len(dry_run_values)
                and dry_run_values[idx]
                and True in dry_run_values[idx]
            ),
        )
        session.config = config

        return dbc.Toast(
            f"Saved settings for Session {session_id[-4:]}\n"
            f"Suite: {config.suite}\n"
            f"Model: {config.model}",
            id="save-success",
            header="Settings Saved",
            is_open=True,
            color="info",
        )

    @app.callback(
        Output("toast-container", "children", allow_duplicate=True),
        Input({"type": "replay-btn", "session": "ALL"}, "n_clicks"),
        State({"type": "suite-dropdown", "session": "ALL"}, "value"),
        State({"type": "iq-dropdown", "session": "ALL"}, "value"),
        State({"type": "model-dropdown", "session": "ALL"}, "value"),
        State({"type": "profile-dropdown", "session": "ALL"}, "value"),
        State({"type": "auto-recover-check", "session": "ALL"}, "value"),
        State({"type": "dry-run-check", "session": "ALL"}, "value"),
        prevent_initial_call=True,
    )
    def handle_replay_button(
        n_clicks_list,
        suite_values,
        iq_values,
        model_values,
        profile_values,
        auto_recover_values,
        dry_run_values,
    ):
        """Handle replay button click - saves settings and runs the test."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        button_data = json.loads(button_id)
        session_id = button_data.get("session")

        if not session_id:
            raise PreventUpdate

        session = session_manager.get_session(session_id)
        if not session:
            return dbc.Toast(
                "Session not found",
                id="replay-error",
                header="Error",
                is_open=True,
                color="danger",
            )

        if session.status == SessionStatus.RUNNING:
            return dbc.Toast(
                "Session is already running",
                id="replay-warning",
                header="Warning",
                is_open=True,
                color="warning",
            )

        # Find the index of this session in the list
        sessions = session_manager.list_sessions()
        session_ids = [s.session_id for s in sessions]
        try:
            idx = session_ids.index(session_id)
        except ValueError:
            idx = 0

        # Save config from UI using the correct index
        config = SessionConfig(
            suite=suite_values[idx]
            if suite_values and idx < len(suite_values)
            else session.config.suite,
            iq_levels=iq_values[idx]
            if iq_values and idx < len(iq_values)
            else session.config.iq_levels,
            model=model_values[idx]
            if model_values and idx < len(model_values)
            else session.config.model,
            profile=profile_values[idx]
            if profile_values and idx < len(profile_values)
            else session.config.profile,
            auto_recover=bool(
                auto_recover_values
                and idx < len(auto_recover_values)
                and auto_recover_values[idx]
                and True in auto_recover_values[idx]
            ),
            dry_run=bool(
                dry_run_values
                and idx < len(dry_run_values)
                and dry_run_values[idx]
                and True in dry_run_values[idx]
            ),
        )
        session.config = config

        # Create and start runner
        runner = RobotRunnerFactory.create_runner(session)
        runner.start()

        return dbc.Toast(
            f"Replaying test run for Session {session_id[-4:]}",
            id="replay-success",
            header="Replaying",
            is_open=True,
            color="warning",
        )

    @app.callback(
        Output({"type": "stop-btn", "session": "ALL"}, "disabled"),
        Input("interval-component", "n_intervals"),
    )
    def update_button_states(n_intervals):
        """Update button states based on session status."""
        sessions = session_manager.list_sessions()
        disabled_states = []

        for session in sessions:
            disabled_states.append(session.status != SessionStatus.RUNNING)

        return disabled_states
