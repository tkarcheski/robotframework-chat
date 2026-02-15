"""Robot Framework Chat Control Panel - Dash application."""

from datetime import datetime

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from dashboard.core.artifact_uploader import upload_session_results
from dashboard.core.docker_network import resolve_node_hostname
from dashboard.core.robot_runner import RobotRunnerFactory
from dashboard.core.session_manager import (
    SessionConfig,
    SessionStatus,
    session_manager,
)
from dashboard.layout import (
    _BORDER,
    _CARD_BG,
    create_app_layout,
    create_session_panel,
)
from dashboard.monitoring import (
    OllamaMonitor,
    PipelineMonitor,
    build_ollama_cards,
    build_pipeline_table,
)
from rfc.suite_config import default_iq_levels, default_model, default_profile

_DEFAULT_HOST = f"{resolve_node_hostname('localhost')}:11434"

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
    Input({"type": "upload-btn", "index": ALL}, "n_clicks"),
    State({"type": "suite-dropdown", "index": ALL}, "value"),
    State({"type": "iq-dropdown", "index": ALL}, "value"),
    State({"type": "host-dropdown", "index": ALL}, "value"),
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
    upload_clicks,
    suites,
    iqs,
    hosts,
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

    # -- Upload to DB --
    if btn_type == "upload-btn":
        if session.status == SessionStatus.RUNNING:
            return _toast("Wait for tests to finish", "Warning", "warning")
        result = upload_session_results(session.session_id)
        if result["status"] == "success":
            return _toast(
                f"Uploaded to database (run_id={result['run_id']})",
                "Uploaded",
                "success",
            )
        return _toast(result["message"], "Upload Failed", "danger")

    # -- Run / Replay --
    if btn_type in ("run-btn", "replay-btn"):
        if session.status == SessionStatus.RUNNING:
            return _toast("Already running", "Warning", "warning")

        # Build config from the form values at this index
        suite_val = suites[idx] if idx < len(suites) else "robot"
        iq_val = iqs[idx] if idx < len(iqs) else default_iq_levels()
        host_val = hosts[idx] if idx < len(hosts) else _DEFAULT_HOST
        model_val = models[idx] if idx < len(models) else default_model()
        profile_val = profiles[idx] if idx < len(profiles) else default_profile()
        ar_val = auto_recovers[idx] if idx < len(auto_recovers) else []
        dr_val = dry_runs[idx] if idx < len(dry_runs) else []

        session.config = SessionConfig(
            suite=suite_val or "robot",
            iq_levels=iq_val or default_iq_levels(),
            model=model_val or default_model(),
            profile=profile_val or default_profile(),
            ollama_host=host_val or _DEFAULT_HOST,
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
    Output({"type": "upload-btn", "index": ALL}, "disabled"),
    Output({"type": "suite-dropdown", "index": ALL}, "disabled"),
    Output({"type": "iq-dropdown", "index": ALL}, "disabled"),
    Output({"type": "host-dropdown", "index": ALL}, "disabled"),
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
    upload_d: list[bool] = []
    suite_d: list[bool] = []
    iq_d: list[bool] = []
    host_d: list[bool] = []
    model_d: list[bool] = []
    profile_d: list[bool] = []
    ar_d: list[bool] = []
    dr_d: list[bool] = []

    for i in range(n):
        if i < len(sessions):
            s = sessions[i]
            running = s.status == SessionStatus.RUNNING
            has_results = s.status in (
                SessionStatus.COMPLETED,
                SessionStatus.FAILED,
            )
        else:
            running = False
            has_results = False
        run_d.append(running)
        stop_d.append(not running)
        replay_d.append(running)
        # Upload enabled only when session has completed or failed (has results)
        upload_d.append(not has_results)
        suite_d.append(running)
        iq_d.append(running)
        host_d.append(running)
        model_d.append(running)
        profile_d.append(running)
        ar_d.append(running)
        dr_d.append(running)

    return (
        run_d,
        stop_d,
        replay_d,
        upload_d,
        suite_d,
        iq_d,
        host_d,
        model_d,
        profile_d,
        ar_d,
        dr_d,
    )


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
                    "borderRadius": "6px 6px 0 0",
                },
                active_label_style={
                    "color": "white",
                    "backgroundColor": s.tab_color,
                    "fontWeight": "bold",
                    "border": f"2px solid {_BORDER}",
                    "borderRadius": "6px 6px 0 0",
                },
            )
        )
    return tabs


# -- Callback 5: switch visible session panel ---------------------------------


_PANEL_SHOW = {
    "display": "block",
    "backgroundColor": _CARD_BG,
    "padding": "16px",
    "borderRadius": "8px",
    "border": f"1px solid {_BORDER}",
}
_PANEL_HIDE = {
    "display": "none",
    "backgroundColor": _CARD_BG,
    "padding": "16px",
    "borderRadius": "8px",
    "border": f"1px solid {_BORDER}",
}


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
        _PANEL_SHOW if p["index"] == active_index else _PANEL_HIDE for p in panel_ids
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


# -- Callback 7: top-level tab switching --------------------------------------


@app.callback(
    Output("top-tab-sessions", "style"),
    Output("top-tab-ollama", "style"),
    Output("top-tab-pipelines", "style"),
    Input("top-tabs", "active_tab"),
)
def switch_top_tab(active_tab):
    """Show only the content panel for the active top-level tab."""
    show = {"display": "block"}
    hide = {"display": "none"}
    return (
        show if active_tab == "top-sessions" else hide,
        show if active_tab == "top-ollama" else hide,
        show if active_tab == "top-pipelines" else hide,
    )


# -- Callback 8: update pipeline table ---------------------------------------


@app.callback(
    Output("pipelines-table", "children"),
    Output("pipelines-last-updated", "children"),
    Input("monitoring-interval", "n_intervals"),
)
def update_pipelines(n_intervals):
    """Fetch and render the GitLab pipelines table."""
    monitor = PipelineMonitor.get()
    monitor.poll_if_due()
    table = build_pipeline_table(monitor.pipelines, monitor=monitor)
    ts = datetime.now().strftime("Updated %H:%M")
    return table, ts


# -- Callback 9: update Ollama host cards -------------------------------------


@app.callback(
    Output("ollama-cards", "children"),
    Input("monitoring-interval", "n_intervals"),
)
def update_ollama(n_intervals):
    """Poll Ollama nodes and rebuild the host cards."""
    monitor = OllamaMonitor.get()
    monitor.poll_if_due()
    return build_ollama_cards(monitor)


# -- Entry point --------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
