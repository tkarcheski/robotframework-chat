"""Dash callbacks for Robot Framework Dashboard."""

from dash import Input, Output, State, MATCH
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
        Output({"type": "console-output", "session": MATCH}, "children"),
        Output({"type": "progress-bar", "session": MATCH}, "value"),
        Output({"type": "progress-bar", "session": MATCH}, "label"),
        Output({"type": "current-test", "session": MATCH}, "children"),
        Input("interval-component", "n_intervals"),
        State({"type": "console-output", "session": MATCH}, "id"),
    )
    def update_live_output(n_intervals, output_id):
        """Update console output and progress for a specific session."""
        session_id = output_id.get("session") if output_id else None
        if not session_id:
            raise PreventUpdate

        session = session_manager.get_session(session_id)
        if not session:
            raise PreventUpdate

        # Console output
        output_text = "\n".join(session.output_buffer)

        # Progress
        if session.progress:
            current = session.progress.get("current", 0)
            total = session.progress.get("total", 1)
            percentage = min(100, int((current / total) * 100))
        else:
            current, total, percentage = 0, 0, 0

        progress_label = f"{percentage}% ({current}/{total})"

        # Current test status
        status_text = f"Status: {session.status.value}"
        if session.current_test:
            status_text += f" | Current: {session.current_test}"

        return output_text, percentage, progress_label, status_text

    @app.callback(
        Output("toast-container", "children", allow_duplicate=True),
        Output({"type": "suite-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "iq-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "model-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "profile-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "auto-recover-check", "session": MATCH}, "disabled"),
        Output({"type": "dry-run-check", "session": MATCH}, "disabled"),
        Output({"type": "run-btn", "session": MATCH}, "disabled"),
        Output({"type": "stop-btn", "session": MATCH}, "disabled"),
        Input({"type": "run-btn", "session": MATCH}, "n_clicks"),
        State({"type": "suite-dropdown", "session": MATCH}, "value"),
        State({"type": "iq-dropdown", "session": MATCH}, "value"),
        State({"type": "model-dropdown", "session": MATCH}, "value"),
        State({"type": "profile-dropdown", "session": MATCH}, "value"),
        State({"type": "auto-recover-check", "session": MATCH}, "value"),
        State({"type": "dry-run-check", "session": MATCH}, "value"),
        State({"type": "run-btn", "session": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def handle_run_button(
        n_clicks,
        suite_value,
        iq_values,
        model_value,
        profile_value,
        auto_recover_value,
        dry_run_value,
        button_id,
    ):
        """Handle run button click."""
        if not n_clicks:
            raise PreventUpdate

        session_id = button_id.get("session") if button_id else None
        if not session_id:
            raise PreventUpdate

        session = session_manager.get_session(session_id)
        if not session:
            return (
                dbc.Toast(
                    "Session not found",
                    id="run-error",
                    header="Error",
                    is_open=True,
                    color="danger",
                ),
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                True,
            )

        if session.status == SessionStatus.RUNNING:
            return (
                dbc.Toast(
                    "Session is already running",
                    id="run-warning",
                    header="Warning",
                    is_open=True,
                    color="warning",
                ),
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                True,
            )

        # Update config from UI values
        config = SessionConfig(
            suite=suite_value if suite_value else session.config.suite,
            iq_levels=iq_values if iq_values else session.config.iq_levels,
            model=model_value if model_value else session.config.model,
            profile=profile_value if profile_value else session.config.profile,
            auto_recover=bool(auto_recover_value and True in auto_recover_value),
            dry_run=bool(dry_run_value and True in dry_run_value),
        )
        session.config = config

        # Create and start runner
        runner = RobotRunnerFactory.create_runner(session)
        runner.start()

        # Disable form fields and run button, enable stop button during execution
        toast = dbc.Toast(
            f"Started test run for Session {session_id[-4:]}",
            id="run-success",
            header="Started",
            is_open=True,
            color="success",
        )

        return (
            toast,
            True,  # suite disabled
            True,  # iq disabled
            True,  # model disabled
            True,  # profile disabled
            True,  # auto-recover disabled
            True,  # dry-run disabled
            True,  # run button disabled
            False,  # stop button enabled
        )

    @app.callback(
        Output("toast-container", "children", allow_duplicate=True),
        Output({"type": "suite-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "iq-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "model-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "profile-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "auto-recover-check", "session": MATCH}, "disabled"),
        Output({"type": "dry-run-check", "session": MATCH}, "disabled"),
        Output({"type": "run-btn", "session": MATCH}, "disabled"),
        Output({"type": "stop-btn", "session": MATCH}, "disabled"),
        Input({"type": "stop-btn", "session": MATCH}, "n_clicks"),
        State({"type": "stop-btn", "session": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def handle_stop_button(n_clicks, button_id):
        """Handle stop button click."""
        if not n_clicks:
            raise PreventUpdate

        session_id = button_id.get("session") if button_id else None
        if not session_id:
            raise PreventUpdate

        success = RobotRunnerFactory.stop_runner(session_id)

        # Re-enable form fields, enable run button, disable stop button
        if success:
            toast = dbc.Toast(
                f"Stopped Session {session_id[-4:]}",
                id="stop-success",
                header="Stopped",
                is_open=True,
                color="info",
            )
        else:
            toast = dbc.Toast(
                "Failed to stop session",
                id="stop-error",
                header="Error",
                is_open=True,
                color="danger",
            )

        return (
            toast,
            False,  # suite enabled
            False,  # iq enabled
            False,  # model enabled
            False,  # profile enabled
            False,  # auto-recover enabled
            False,  # dry-run enabled
            False,  # run button enabled
            True,  # stop button disabled
        )

    @app.callback(
        Output("toast-container", "children", allow_duplicate=True),
        Input({"type": "replay-btn", "session": MATCH}, "n_clicks"),
        State({"type": "replay-btn", "session": MATCH}, "id"),
        State({"type": "suite-dropdown", "session": MATCH}, "value"),
        State({"type": "iq-dropdown", "session": MATCH}, "value"),
        State({"type": "model-dropdown", "session": MATCH}, "value"),
        State({"type": "profile-dropdown", "session": MATCH}, "value"),
        State({"type": "auto-recover-check", "session": MATCH}, "value"),
        State({"type": "dry-run-check", "session": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def handle_replay_button(
        n_clicks,
        button_id,
        suite_value,
        iq_values,
        model_value,
        profile_value,
        auto_recover_value,
        dry_run_value,
    ):
        """Handle replay button click - runs with current settings."""
        if not n_clicks:
            raise PreventUpdate

        session_id = button_id.get("session") if button_id else None
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

        # Update config from UI values
        config = SessionConfig(
            suite=suite_value if suite_value else session.config.suite,
            iq_levels=iq_values if iq_values else session.config.iq_levels,
            model=model_value if model_value else session.config.model,
            profile=profile_value if profile_value else session.config.profile,
            auto_recover=bool(auto_recover_value and True in auto_recover_value),
            dry_run=bool(dry_run_value and True in dry_run_value),
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
        Output("toast-container", "children", allow_duplicate=True),
        Input({"type": "save-btn", "session": MATCH}, "n_clicks"),
        State({"type": "save-btn", "session": MATCH}, "id"),
        State({"type": "suite-dropdown", "session": MATCH}, "value"),
        State({"type": "iq-dropdown", "session": MATCH}, "value"),
        State({"type": "model-dropdown", "session": MATCH}, "value"),
        State({"type": "profile-dropdown", "session": MATCH}, "value"),
        State({"type": "auto-recover-check", "session": MATCH}, "value"),
        State({"type": "dry-run-check", "session": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def handle_save_button(
        n_clicks,
        button_id,
        suite_value,
        iq_values,
        model_value,
        profile_value,
        auto_recover_value,
        dry_run_value,
    ):
        """Handle save button click - saves current settings to session config."""
        if not n_clicks:
            raise PreventUpdate

        session_id = button_id.get("session") if button_id else None
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

        # Save config from UI values
        config = SessionConfig(
            suite=suite_value if suite_value else session.config.suite,
            iq_levels=iq_values if iq_values else session.config.iq_levels,
            model=model_value if model_value else session.config.model,
            profile=profile_value if profile_value else session.config.profile,
            auto_recover=bool(auto_recover_value and True in auto_recover_value),
            dry_run=bool(dry_run_value and True in dry_run_value),
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
        Output({"type": "stop-btn", "session": MATCH}, "disabled"),
        Output({"type": "run-btn", "session": MATCH}, "disabled"),
        Output({"type": "replay-btn", "session": MATCH}, "disabled"),
        Output({"type": "suite-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "iq-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "model-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "profile-dropdown", "session": MATCH}, "disabled"),
        Output({"type": "auto-recover-check", "session": MATCH}, "disabled"),
        Output({"type": "dry-run-check", "session": MATCH}, "disabled"),
        Input("interval-component", "n_intervals"),
        State({"type": "stop-btn", "session": MATCH}, "id"),
    )
    def update_button_states(n_intervals, button_id):
        """Update button states based on session status."""
        if not button_id:
            raise PreventUpdate

        session_id = button_id.get("session")
        if not session_id:
            raise PreventUpdate

        session = session_manager.get_session(session_id)
        if not session:
            # Default state: all enabled except stop
            return False, False, False, False, False, False, False, False, False

        is_running = session.status == SessionStatus.RUNNING

        # When running: disable form fields, run, replay; enable stop
        # When not running: enable form fields, run, replay; disable stop
        return (
            not is_running,  # stop-btn: disabled when not running
            is_running,  # run-btn: disabled when running
            is_running,  # replay-btn: disabled when running
            is_running,  # suite: disabled when running
            is_running,  # iq: disabled when running
            is_running,  # model: disabled when running
            is_running,  # profile: disabled when running
            is_running,  # auto-recover: disabled when running
            is_running,  # dry-run: disabled when running
        )
