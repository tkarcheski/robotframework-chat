"""Main Dash application for Robot Framework Dashboard."""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from dashboard.core.llm_registry import llm_registry
from dashboard.core.session_manager import (
    RobotSession,
    SessionConfig,
    SessionStatus,
    session_manager,
)
from dashboard.callbacks.execution_callbacks import (
    register_callbacks as register_execution_callbacks,
)

# Initialize Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
)
app.title = "Robot Framework Dashboard"

# Available test suites
TEST_SUITES = [
    {"label": "Math Tests", "value": "robot/math/tests"},
    {"label": "Docker Python", "value": "robot/docker/python/tests"},
    {"label": "Docker LLM", "value": "robot/docker/llm/tests"},
    {"label": "Docker Shell", "value": "robot/docker/shell/tests"},
    {"label": "Safety Tests", "value": "robot/safety/test_cases"},
]

# IQ levels
IQ_LEVELS = [
    {"label": "100", "value": "100"},
    {"label": "110", "value": "110"},
    {"label": "120", "value": "120"},
    {"label": "130", "value": "130"},
    {"label": "140", "value": "140"},
    {"label": "150", "value": "150"},
    {"label": "160", "value": "160"},
]

# Container profiles
CONTAINER_PROFILES = [
    {"label": "Minimal (0.25 CPU, 128MB)", "value": "MINIMAL"},
    {"label": "Standard (0.5 CPU, 512MB)", "value": "STANDARD"},
    {"label": "Performance (1.0 CPU, 1GB)", "value": "PERFORMANCE"},
    {"label": "Ollama CPU (2.0 CPU, 4GB)", "value": "OLLAMA_CPU"},
]


def create_session_tab(session: RobotSession) -> dbc.Tab:
    """Create a colored tab for a session."""
    return dbc.Tab(
        label=session.tab_label,
        tab_id=f"tab-{session.session_id}",
        label_style={
            "color": "white",
            "backgroundColor": session.tab_color,
            "fontWeight": "bold",
        },
        active_label_style={
            "color": "white",
            "backgroundColor": session.tab_color,
            "fontWeight": "bold",
            "border": "2px solid white",
        },
    )


def create_settings_panel(session_id: str | None = None) -> html.Div:
    """Create the settings panel for a session."""
    session = session_manager.get_session(session_id) if session_id else None
    config = session.config if session else SessionConfig()

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Test Suite"),
                            dcc.Dropdown(
                                id={"type": "suite-dropdown", "session": session_id},
                                options=TEST_SUITES,
                                value=config.suite,
                                placeholder="Select test suite...",
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("IQ Levels"),
                            dcc.Dropdown(
                                id={"type": "iq-dropdown", "session": session_id},
                                options=IQ_LEVELS,
                                value=config.iq_levels,
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
                                id={"type": "model-dropdown", "session": session_id},
                                options=[
                                    {"label": m, "value": m}
                                    for m in llm_registry.get_models()
                                ],
                                value=config.model,
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
                                id={"type": "profile-dropdown", "session": session_id},
                                options=CONTAINER_PROFILES,
                                value=config.profile,
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
                                value=[True] if config.auto_recover else [],
                                id={
                                    "type": "auto-recover-check",
                                    "session": session_id,
                                },
                                switch=True,
                            ),
                            dbc.Checklist(
                                options=[
                                    {"label": " Dry run", "value": True},
                                ],
                                value=[True] if config.dry_run else [],
                                id={"type": "dry-run-check", "session": session_id},
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
                                        id={"type": "run-btn", "session": session_id},
                                        color="success",
                                        className="me-2",
                                    ),
                                    dbc.Button(
                                        "⏹️ Stop",
                                        id={"type": "stop-btn", "session": session_id},
                                        color="danger",
                                        className="me-2",
                                        disabled=not session
                                        or session.status != SessionStatus.RUNNING,
                                    ),
                                    dbc.Button(
                                        "🔄 Replay",
                                        id={
                                            "type": "replay-btn",
                                            "session": session_id,
                                        },
                                        color="warning",
                                        className="me-2",
                                    ),
                                    dbc.Button(
                                        "💾 Save",
                                        id={"type": "save-btn", "session": session_id},
                                        color="info",
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
    )


def create_execution_panel(session_id: str | None = None) -> html.Div:
    """Create the execution panel with progress bar."""
    session = session_manager.get_session(session_id) if session_id else None

    if session and session.progress:
        current = session.progress.get("current", 0)
        total = session.progress.get("total", 1)
        percentage = min(100, int((current / total) * 100))
    else:
        current, total, percentage = 0, 0, 0

    return html.Div(
        [
            dbc.Progress(
                id={"type": "progress-bar", "session": session_id},
                value=percentage,
                label=f"{percentage}% ({current}/{total})",
                striped=True,
                animated=session and session.status == SessionStatus.RUNNING,
                className="mb-2",
            ),
            html.Div(
                id={"type": "current-test", "session": session_id},
                children=f"Current: {session.current_test if session else 'Idle'}",
                className="text-muted",
            ),
        ],
        className="p-3 border rounded mb-3",
    )


def create_output_panel(session_id: str | None = None) -> html.Div:
    """Create the live console output panel."""
    session = session_manager.get_session(session_id) if session_id else None

    output_text = ""
    if session:
        output_text = "\n".join(session.output_buffer)

    return html.Div(
        [
            html.H5("Console Output"),
            html.Pre(
                id={"type": "console-output", "session": session_id},
                children=output_text,
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
                id={"type": "auto-scroll-check", "session": session_id},
                switch=True,
                inline=True,
            ),
        ],
        className="p-3 border rounded",
    )


def create_results_panel(session_id: str | None = None) -> html.Div:
    """Create the test results panel."""
    return html.Div(
        [
            html.H5("Test Results"),
            html.Div(
                id={"type": "results-table", "session": session_id},
                children="No results yet...",
            ),
        ],
        className="p-3 border rounded",
    )


# Main app layout
app.layout = html.Div(
    [
        # Store components for state management
        dcc.Store(id="active-session", data=None),
        dcc.Store(id="session-list", data=[]),
        # Header
        dbc.Navbar(
            dbc.Container(
                [
                    html.H1(
                        "Robot Framework Dashboard",
                        className="text-white mb-0",
                    ),
                    dbc.Button(
                        "➕ New Session",
                        id="new-session-btn",
                        color="primary",
                        className="ms-auto",
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
                # Session tabs
                dbc.Tabs(
                    id="session-tabs",
                    active_tab=None,
                    children=[],
                ),
                # Session content area
                html.Div(id="session-content"),
                # History section
                html.Hr(className="my-4"),
                html.H3("Test Run History"),
                html.Div(id="history-table"),
            ],
            fluid=True,
            className="px-4",
        ),
        # Interval for live updates (500ms)
        dcc.Interval(id="interval-component", interval=500),
        # Toast notifications
        html.Div(id="toast-container"),
    ]
)


register_execution_callbacks(app)


@app.callback(
    Output("session-tabs", "children"),
    Output("session-list", "data"),
    Input("interval-component", "n_intervals"),
    State("session-list", "data"),
)
def update_session_tabs(n_intervals, current_sessions):
    """Update session tabs with current status and runtime."""
    sessions = session_manager.list_sessions()

    tabs = []
    session_ids = []

    for session in sessions:
        tabs.append(create_session_tab(session))
        session_ids.append(session.session_id)

    return tabs, session_ids


@app.callback(
    Output("active-session", "data"),
    Output("session-tabs", "active_tab"),
    Input("session-tabs", "active_tab"),
)
def update_active_session(active_tab):
    """Update the active session ID."""
    if active_tab:
        session_id = active_tab.replace("tab-", "")
        return session_id, active_tab
    return None, None


@app.callback(
    Output("session-content", "children"),
    Input("active-session", "data"),
)
def render_session_content(session_id):
    """Render content for the active session."""
    if not session_id:
        return html.Div(
            html.H4(
                "Select or create a session to begin",
                className="text-center text-muted my-5",
            )
        )

    return html.Div(
        [
            create_settings_panel(session_id),
            create_execution_panel(session_id),
            dbc.Row(
                [
                    dbc.Col(create_output_panel(session_id), width=6),
                    dbc.Col(create_results_panel(session_id), width=6),
                ]
            ),
        ]
    )


@app.callback(
    Output("toast-container", "children"),
    Input("new-session-btn", "n_clicks"),
    prevent_initial_call=True,
)
def create_new_session(n_clicks):
    """Create a new session when button is clicked."""
    if not n_clicks:
        raise PreventUpdate

    try:
        session = session_manager.create_session(SessionConfig())
        return dbc.Toast(
            f"Created Session {session.session_id[-4:]}",
            id="new-session-toast",
            header="Success",
            is_open=True,
            dismissable=True,
            duration=3000,
            color="success",
        )
    except Exception as e:
        return dbc.Toast(
            str(e),
            id="new-session-error",
            header="Error",
            is_open=True,
            dismissable=True,
            duration=5000,
            color="danger",
        )


if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=8050)
