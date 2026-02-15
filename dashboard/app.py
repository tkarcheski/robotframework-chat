"""Robot Framework Chat Control Panel - Dash application."""

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from dashboard.core.robot_runner import RobotRunnerFactory
from dashboard.core.session_manager import (
    SessionConfig,
    SessionStatus,
    session_manager,
)
from dashboard.layout import create_app_layout, create_session_panel
from rfc.suite_config import default_iq_levels, default_model, default_profile

# -- App init ----------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
)
app.title = "Robot Framework Chat Control Panel"

# Create the first session at startup
session_manager.create_session(SessionConfig())

# Assign layout (built once; all panels live in the DOM)
app.layout = create_app_layout()


# -- Callback 1: handle ALL button clicks ------------------------------------
# ONE callback for Run / Stop / Replay / Delete.
# This is the ONLY callback that writes to "toast-container.children".


@app.callback(
    Output("toast-container", "children"),
    Input({"type": "run-btn", "index": ALL}, "n_clicks"),
    Input({"type": "stop-btn", "index": ALL}, "n_clicks"),
    Input({"type": "replay-btn", "index": ALL}, "n_clicks"),
    Input({"type": "delete-btn", "index": ALL}, "n_clicks"),
    State({"type": "suite-dropdown", "index": ALL}, "value"),
    State({"type": "iq-dropdown", "index": ALL}, "value"),
    State({"type": "model-dropdown", "index": ALL}, "value"),
    State({"type": "profile-dropdown", "index": ALL}, "value"),
    State({"type": "auto-recover-check", "index": ALL}, "value"),
    State({"type": "dry-run-check", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def handle_button_click(
    run_clicks,
    stop_clicks,
    replay_clicks,
    delete_clicks,
    suites,
    iqs,
    models,
    profiles,
    auto_recovers,
    dry_runs,
):
    """Single handler for every action button across all sessions."""
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        raise PreventUpdate

    btn_type = triggered["type"]
    idx = triggered["index"]

    sessions = session_manager.list_sessions()
    if idx >= len(sessions):
        raise PreventUpdate
    session = sessions[idx]

    # -- Stop --
    if btn_type == "stop-btn":
        RobotRunnerFactory.stop_runner(session.session_id)
        return _toast("Stopped test run", "Stopped", "info")

    # -- Delete --
    if btn_type == "delete-btn":
        if session.status == SessionStatus.RUNNING:
            RobotRunnerFactory.stop_runner(session.session_id)
        session_manager.close_session(session.session_id)
        return _toast("Session deleted", "Deleted", "secondary")

    # -- Run / Replay --
    if btn_type in ("run-btn", "replay-btn"):
        if session.status == SessionStatus.RUNNING:
            return _toast("Already running", "Warning", "warning")

        # Build config from the form values at this index
        suite_val = suites[idx] if idx < len(suites) else "robot"
        iq_val = iqs[idx] if idx < len(iqs) else default_iq_levels()
        model_val = models[idx] if idx < len(models) else default_model()
        profile_val = profiles[idx] if idx < len(profiles) else default_profile()
        ar_val = auto_recovers[idx] if idx < len(auto_recovers) else []
        dr_val = dry_runs[idx] if idx < len(dry_runs) else []

        session.config = SessionConfig(
            suite=suite_val or "robot",
            iq_levels=iq_val or default_iq_levels(),
            model=model_val or default_model(),
            profile=profile_val or default_profile(),
            auto_recover=bool(ar_val and True in ar_val),
            dry_run=bool(dr_val and True in dr_val),
        )

        runner = RobotRunnerFactory.create_runner(session)
        runner.start()
        label = "Replaying" if btn_type == "replay-btn" else "Started"
        return _toast(f"{label} test run", label, "success")

    raise PreventUpdate


def _toast(msg: str, header: str, color: str) -> dbc.Toast:
    return dbc.Toast(
        msg,
        id="action-toast",
        header=header,
        is_open=True,
        dismissable=True,
        duration=3000,
        color=color,
    )


# -- Callback 2: poll live output for ALL sessions ----------------------------


@app.callback(
    Output({"type": "console-output", "index": ALL}, "children"),
    Output({"type": "progress-bar", "index": ALL}, "value"),
    Output({"type": "progress-bar", "index": ALL}, "label"),
    Output({"type": "current-test", "index": ALL}, "children"),
    Input("interval-component", "n_intervals"),
    State({"type": "console-output", "index": ALL}, "id"),
)
def update_live_output(n_intervals, panel_ids):
    """Push console text and progress for every session panel."""
    sessions = session_manager.list_sessions()
    n = len(panel_ids)

    console_texts: list[str] = []
    progress_values: list[int] = []
    progress_labels: list[str] = []
    current_tests: list[str] = []

    for i in range(n):
        if i < len(sessions):
            s = sessions[i]
            console_texts.append("\n".join(s.output_buffer))
            cur = s.progress.get("current", 0)
            tot = s.progress.get("total", 0)
            pct = min(100, int((cur / tot) * 100)) if tot else 0
            progress_values.append(pct)
            progress_labels.append(f"{pct}% ({cur}/{tot})" if tot else "Idle")
            status = f"Status: {s.status.value}"
            if s.current_test:
                status += f" | {s.current_test}"
            current_tests.append(status)
        else:
            # Panel exists but session was deleted
            console_texts.append("")
            progress_values.append(0)
            progress_labels.append("Idle")
            current_tests.append("Session deleted")

    return console_texts, progress_values, progress_labels, current_tests


# -- Callback 3: update button disabled states for ALL sessions ---------------


@app.callback(
    Output({"type": "run-btn", "index": ALL}, "disabled"),
    Output({"type": "stop-btn", "index": ALL}, "disabled"),
    Output({"type": "replay-btn", "index": ALL}, "disabled"),
    Output({"type": "suite-dropdown", "index": ALL}, "disabled"),
    Output({"type": "iq-dropdown", "index": ALL}, "disabled"),
    Output({"type": "model-dropdown", "index": ALL}, "disabled"),
    Output({"type": "profile-dropdown", "index": ALL}, "disabled"),
    Output({"type": "auto-recover-check", "index": ALL}, "disabled"),
    Output({"type": "dry-run-check", "index": ALL}, "disabled"),
    Input("interval-component", "n_intervals"),
    State({"type": "run-btn", "index": ALL}, "id"),
)
def update_ui_states(n_intervals, btn_ids):
    """Enable / disable controls based on running state."""
    sessions = session_manager.list_sessions()
    n = len(btn_ids)

    run_d: list[bool] = []
    stop_d: list[bool] = []
    replay_d: list[bool] = []
    suite_d: list[bool] = []
    iq_d: list[bool] = []
    model_d: list[bool] = []
    profile_d: list[bool] = []
    ar_d: list[bool] = []
    dr_d: list[bool] = []

    for i in range(n):
        running = i < len(sessions) and sessions[i].status == SessionStatus.RUNNING
        run_d.append(running)
        stop_d.append(not running)
        replay_d.append(running)
        suite_d.append(running)
        iq_d.append(running)
        model_d.append(running)
        profile_d.append(running)
        ar_d.append(running)
        dr_d.append(running)

    return run_d, stop_d, replay_d, suite_d, iq_d, model_d, profile_d, ar_d, dr_d


# -- Callback 4: update tab labels / colours ---------------------------------


@app.callback(
    Output("session-tabs", "children"),
    Input("interval-component", "n_intervals"),
)
def update_tab_styles(n_intervals):
    """Rebuild tabs with status colours and runtime."""
    sessions = session_manager.list_sessions()
    tabs = []
    for i, s in enumerate(sessions):
        tabs.append(
            dbc.Tab(
                label=s.tab_label,
                tab_id=f"tab-{i}",
                label_style={
                    "color": "white",
                    "backgroundColor": s.tab_color,
                    "fontWeight": "bold",
                },
                active_label_style={
                    "color": "white",
                    "backgroundColor": s.tab_color,
                    "fontWeight": "bold",
                    "border": "2px solid white",
                },
            )
        )
    return tabs


# -- Callback 5: switch visible session panel ---------------------------------


@app.callback(
    Output({"type": "session-panel", "index": ALL}, "style"),
    Input("session-tabs", "active_tab"),
    State({"type": "session-panel", "index": ALL}, "id"),
)
def toggle_tab_visibility(active_tab, panel_ids):
    """Show only the panel for the active tab; hide others."""
    if not active_tab:
        raise PreventUpdate
    active_index = int(active_tab.replace("tab-", ""))
    return [
        {"display": "block"} if p["index"] == active_index else {"display": "none"}
        for p in panel_ids
    ]


# -- Callback 6: add new session ---------------------------------------------


@app.callback(
    Output("sessions-container", "children"),
    Output("session-tabs", "active_tab"),
    Output("session-counter", "data"),
    Input("new-session-btn", "n_clicks"),
    State("sessions-container", "children"),
    State("session-counter", "data"),
    prevent_initial_call=True,
)
def add_new_session(n_clicks, current_panels, counter):
    """Create a new session and add its panel to the DOM."""
    if not n_clicks:
        raise PreventUpdate

    sessions = session_manager.list_sessions()
    if len(sessions) >= 5:
        return current_panels, f"tab-{counter - 1}", counter

    session_manager.create_session(SessionConfig())
    new_index = counter
    current_panels.append(create_session_panel(new_index))

    return current_panels, f"tab-{new_index}", counter + 1


# -- Entry point --------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
