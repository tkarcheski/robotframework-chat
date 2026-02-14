"""Simplified Robot Framework Dashboard - Single Session."""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from dashboard.core.llm_registry import llm_registry
from dashboard.core.robot_runner import RobotRunnerFactory
from dashboard.core.session_manager import SessionConfig, SessionStatus, session_manager

# Initialize Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
app.title = "Robot Framework Chat Control Panel"

# Test configuration options
TEST_SUITES = [
    {"label": "Run All Test Suites", "value": "robot"},
    {"label": "Math Tests", "value": "robot/math/tests"},
    {"label": "Docker Python", "value": "robot/docker/python/tests"},
    {"label": "Docker LLM", "value": "robot/docker/llm/tests"},
    {"label": "Docker Shell", "value": "robot/docker/shell/tests"},
    {"label": "Safety Tests", "value": "robot/safety/test_cases"},
]

IQ_LEVELS = [
    {"label": "100", "value": "100"},
    {"label": "110", "value": "110"},
    {"label": "120", "value": "120"},
    {"label": "130", "value": "130"},
    {"label": "140", "value": "140"},
    {"label": "150", "value": "150"},
    {"label": "160", "value": "160"},
]

CONTAINER_PROFILES = [
    {"label": "Minimal (0.25 CPU, 128MB)", "value": "MINIMAL"},
    {"label": "Standard (0.5 CPU, 512MB)", "value": "STANDARD"},
    {"label": "Performance (1.0 CPU, 1GB)", "value": "PERFORMANCE"},
]

# Create a single default session on startup
_default_session = session_manager.create_session(SessionConfig())
SESSION_ID = _default_session.session_id

# Main layout
app.layout = html.Div(
    [
        # Header
        dbc.Navbar(
            dbc.Container(
                [
                    html.H1(
                        "Robot Framework Chat Control Panel",
                        className="text-white mb-0",
                    ),
                ]
            ),
            color="dark",
            dark=True,
            className="mb-4",
        ),
        # Main content
        dbc.Container(
            [
                # Settings Panel
                html.Div(
                    [
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label("Test Suite"),
                                        dcc.Dropdown(
                                            id="suite-dropdown",
                                            options=TEST_SUITES,
                                            value="robot",
                                            placeholder="Select test suite...",
                                        ),
                                    ],
                                    width=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("IQ Levels"),
                                        dcc.Dropdown(
                                            id="iq-dropdown",
                                            options=IQ_LEVELS,
                                            value=["100", "110", "120"],
                                            multi=True,
                                            placeholder="Select IQ levels...",
                                        ),
                                    ],
                                    width=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("LLM Model"),
                                        dcc.Dropdown(
                                            id="model-dropdown",
                                            options=[
                                                {"label": m, "value": m}
                                                for m in llm_registry.get_models()
                                            ]
                                            or [{"label": "llama3", "value": "llama3"}],
                                            value="llama3",
                                            placeholder="Select LLM model...",
                                        ),
                                    ],
                                    width=4,
                                ),
                            ],
                            className="mb-3",
                        ),
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label("Container Profile"),
                                        dcc.Dropdown(
                                            id="profile-dropdown",
                                            options=CONTAINER_PROFILES,
                                            value="STANDARD",
                                        ),
                                    ],
                                    width=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Checklist(
                                            options=[
                                                {
                                                    "label": " Auto-recover on failure",
                                                    "value": True,
                                                },
                                            ],
                                            value=[],
                                            id="auto-recover-check",
                                            switch=True,
                                        ),
                                        dbc.Checklist(
                                            options=[
                                                {"label": " Dry run", "value": True}
                                            ],
                                            value=[],
                                            id="dry-run-check",
                                            switch=True,
                                        ),
                                    ],
                                    width=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.ButtonGroup(
                                            [
                                                dbc.Button(
                                                    "▶️ Run",
                                                    id="run-btn",
                                                    color="success",
                                                    className="me-2",
                                                ),
                                                dbc.Button(
                                                    "⏹️ Stop",
                                                    id="stop-btn",
                                                    color="danger",
                                                    className="me-2",
                                                ),
                                                dbc.Button(
                                                    "🔄 Replay",
                                                    id="replay-btn",
                                                    color="warning",
                                                    className="me-2",
                                                ),
                                            ]
                                        ),
                                    ],
                                    width=4,
                                    className="d-flex align-items-end",
                                ),
                            ],
                            className="mb-3",
                        ),
                    ],
                    className="p-3 border rounded",
                ),
                # Progress Bar
                html.Div(
                    [
                        dbc.Progress(
                            id="progress-bar",
                            value=0,
                            label="0% (0/0)",
                            className="mb-2",
                        ),
                        html.Div(
                            id="current-test",
                            children="Current: Idle",
                            className="text-muted",
                        ),
                    ],
                    className="p-3 border rounded mb-3",
                ),
                # Console Output and Results
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.H5("Console Output"),
                                html.Pre(
                                    id="console-output",
                                    children="",
                                    style={
                                        "height": "300px",
                                        "overflow": "auto",
                                        "backgroundColor": "#1e1e1e",
                                        "color": "#d4d4d4",
                                        "padding": "10px",
                                        "fontFamily": "monospace",
                                        "fontSize": "12px",
                                        "border": "1px solid #444",
                                        "borderRadius": "4px",
                                    },
                                ),
                                dbc.Checklist(
                                    options=[{"label": " Auto-scroll", "value": True}],
                                    value=[True],
                                    id="auto-scroll-check",
                                    switch=True,
                                    inline=True,
                                ),
                            ],
                            width=6,
                        ),
                        dbc.Col(
                            [
                                html.H5("Test Results"),
                                html.Div(
                                    id="results-table",
                                    children="No results yet...",
                                ),
                            ],
                            width=6,
                        ),
                    ]
                ),
            ],
            fluid=True,
            className="px-4",
        ),
        # Interval for live updates
        dcc.Interval(id="interval-component", interval=500),
        # Toast notifications
        html.Div(id="toast-container"),
    ]
)


# Live update callback
@app.callback(
    Output("console-output", "children"),
    Output("progress-bar", "value"),
    Output("progress-bar", "label"),
    Output("current-test", "children"),
    Input("interval-component", "n_intervals"),
)
def update_live_output(n_intervals):
    """Update console output and progress."""
    session = session_manager.get_session(SESSION_ID)
    if not session:
        raise PreventUpdate

    output_text = "\n".join(session.output_buffer)

    if session.progress:
        current = session.progress.get("current", 0)
        total = session.progress.get("total", 1)
        percentage = min(100, int((current / total) * 100))
    else:
        current, total, percentage = 0, 0, 0

    progress_label = f"{percentage}% ({current}/{total})"
    status_text = f"Status: {session.status.value}"
    if session.current_test:
        status_text += f" | Current: {session.current_test}"

    return output_text, percentage, progress_label, status_text


# Run button callback
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Output("run-btn", "disabled"),
    Output("stop-btn", "disabled"),
    Output("replay-btn", "disabled"),
    Output("suite-dropdown", "disabled"),
    Output("iq-dropdown", "disabled"),
    Output("model-dropdown", "disabled"),
    Output("profile-dropdown", "disabled"),
    Output("auto-recover-check", "disabled"),
    Output("dry-run-check", "disabled"),
    Input("run-btn", "n_clicks"),
    State("suite-dropdown", "value"),
    State("iq-dropdown", "value"),
    State("model-dropdown", "value"),
    State("profile-dropdown", "value"),
    State("auto-recover-check", "value"),
    State("dry-run-check", "value"),
    prevent_initial_call=True,
)
def handle_run(
    n_clicks,
    suite_value,
    iq_values,
    model_value,
    profile_value,
    auto_recover_value,
    dry_run_value,
):
    """Handle run button click."""
    if not n_clicks:
        raise PreventUpdate

    session = session_manager.get_session(SESSION_ID)
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
            False,
            False,
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
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    # Update config from UI values
    config = SessionConfig(
        suite=suite_value or "robot",
        iq_levels=iq_values or ["100", "110", "120"],
        model=model_value or "llama3",
        profile=profile_value or "STANDARD",
        auto_recover=bool(auto_recover_value and True in auto_recover_value),
        dry_run=bool(dry_run_value and True in dry_run_value),
    )
    session.config = config

    # Create and start runner
    runner = RobotRunnerFactory.create_runner(session)
    runner.start()

    toast = dbc.Toast(
        "Started test run",
        id="run-success",
        header="Started",
        is_open=True,
        color="success",
    )

    # Disable controls during execution
    return (
        toast,
        True,  # run disabled
        False,  # stop enabled
        True,  # replay disabled
        True,  # suite disabled
        True,  # iq disabled
        True,  # model disabled
        True,  # profile disabled
        True,  # auto-recover disabled
        True,  # dry-run disabled
    )


# Stop button callback
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Output("run-btn", "disabled"),
    Output("stop-btn", "disabled"),
    Output("replay-btn", "disabled"),
    Output("suite-dropdown", "disabled"),
    Output("iq-dropdown", "disabled"),
    Output("model-dropdown", "disabled"),
    Output("profile-dropdown", "disabled"),
    Output("auto-recover-check", "disabled"),
    Output("dry-run-check", "disabled"),
    Input("stop-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_stop(n_clicks):
    """Handle stop button click."""
    if not n_clicks:
        raise PreventUpdate

    success = RobotRunnerFactory.stop_runner(SESSION_ID)

    toast = dbc.Toast(
        "Stopped test run" if success else "Failed to stop",
        id="stop-success" if success else "stop-error",
        header="Stopped" if success else "Error",
        is_open=True,
        color="info" if success else "danger",
    )

    # Re-enable controls
    return (
        toast,
        False,  # run enabled
        True,  # stop disabled
        False,  # replay enabled
        False,  # suite enabled
        False,  # iq enabled
        False,  # model enabled
        False,  # profile enabled
        False,  # auto-recover enabled
        False,  # dry-run enabled
    )


# Replay button callback
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Output("run-btn", "disabled"),
    Output("stop-btn", "disabled"),
    Output("replay-btn", "disabled"),
    Output("suite-dropdown", "disabled"),
    Output("iq-dropdown", "disabled"),
    Output("model-dropdown", "disabled"),
    Output("profile-dropdown", "disabled"),
    Output("auto-recover-check", "disabled"),
    Output("dry-run-check", "disabled"),
    Input("replay-btn", "n_clicks"),
    State("suite-dropdown", "value"),
    State("iq-dropdown", "value"),
    State("model-dropdown", "value"),
    State("profile-dropdown", "value"),
    State("auto-recover-check", "value"),
    State("dry-run-check", "value"),
    prevent_initial_call=True,
)
def handle_replay(
    n_clicks,
    suite_value,
    iq_values,
    model_value,
    profile_value,
    auto_recover_value,
    dry_run_value,
):
    """Handle replay button click."""
    if not n_clicks:
        raise PreventUpdate

    session = session_manager.get_session(SESSION_ID)
    if not session:
        return (
            dbc.Toast(
                "Session not found",
                id="replay-error",
                header="Error",
                is_open=True,
                color="danger",
            ),
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    # Update config from UI values
    config = SessionConfig(
        suite=suite_value or "robot",
        iq_levels=iq_values or ["100", "110", "120"],
        model=model_value or "llama3",
        profile=profile_value or "STANDARD",
        auto_recover=bool(auto_recover_value and True in auto_recover_value),
        dry_run=bool(dry_run_value and True in dry_run_value),
    )
    session.config = config

    # Create and start runner
    runner = RobotRunnerFactory.create_runner(session)
    runner.start()

    toast = dbc.Toast(
        "Replaying test run",
        id="replay-success",
        header="Replaying",
        is_open=True,
        color="warning",
    )

    # Disable controls during execution
    return (
        toast,
        True,  # run disabled
        False,  # stop enabled
        True,  # replay disabled
        True,  # suite disabled
        True,  # iq disabled
        True,  # model disabled
        True,  # profile disabled
        True,  # auto-recover disabled
        True,  # dry-run disabled
    )


# Update button states based on session status
@app.callback(
    Output("stop-btn", "disabled"),
    Output("run-btn", "disabled"),
    Output("replay-btn", "disabled"),
    Output("suite-dropdown", "disabled"),
    Output("iq-dropdown", "disabled"),
    Output("model-dropdown", "disabled"),
    Output("profile-dropdown", "disabled"),
    Output("auto-recover-check", "disabled"),
    Output("dry-run-check", "disabled"),
    Input("interval-component", "n_intervals"),
)
def update_button_states(n_intervals):
    """Update button states based on session status."""
    session = session_manager.get_session(SESSION_ID)
    if not session:
        # Default state: all enabled except stop
        return True, False, False, False, False, False, False, False, False

    is_running = session.status == SessionStatus.RUNNING

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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
