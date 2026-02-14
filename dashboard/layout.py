"""Layout builder functions for the dashboard. Pure HTML, no callbacks."""

import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.core.llm_registry import llm_registry

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


def _model_options() -> list[dict]:
    """Get LLM model options from Ollama, with a fallback."""
    models = llm_registry.get_models()
    if models:
        return [{"label": m, "value": m} for m in models]
    return [{"label": "llama3", "value": "llama3"}]


def create_session_panel(index: int) -> html.Div:
    """Create a complete session panel for the given index.

    Each component ID is a dict like {"type": "suite-dropdown", "index": 0}.
    """
    idx = {"index": index}

    return html.Div(
        id={"type": "session-panel", **idx},
        style={"display": "block" if index == 0 else "none"},
        children=[
            # Settings row 1: dropdowns
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Test Suite"),
                            dcc.Dropdown(
                                id={"type": "suite-dropdown", **idx},
                                options=TEST_SUITES,
                                value="robot",
                                clearable=False,
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("IQ Levels"),
                            dcc.Dropdown(
                                id={"type": "iq-dropdown", **idx},
                                options=IQ_LEVELS,
                                value=["100", "110", "120"],
                                multi=True,
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("LLM Model"),
                            dcc.Dropdown(
                                id={"type": "model-dropdown", **idx},
                                options=_model_options(),
                                value="llama3",
                                clearable=False,
                            ),
                        ],
                        width=4,
                    ),
                ],
                className="mb-3",
            ),
            # Settings row 2: profile, switches, buttons
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Container Profile"),
                            dcc.Dropdown(
                                id={"type": "profile-dropdown", **idx},
                                options=CONTAINER_PROFILES,
                                value="STANDARD",
                                clearable=False,
                            ),
                        ],
                        width=3,
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
                                id={"type": "auto-recover-check", **idx},
                                switch=True,
                            ),
                            dbc.Checklist(
                                options=[{"label": " Dry run", "value": True}],
                                value=[],
                                id={"type": "dry-run-check", **idx},
                                switch=True,
                            ),
                        ],
                        width=3,
                    ),
                    dbc.Col(
                        [
                            dbc.ButtonGroup(
                                [
                                    dbc.Button(
                                        "Run",
                                        id={"type": "run-btn", **idx},
                                        color="success",
                                        className="me-1",
                                    ),
                                    dbc.Button(
                                        "Stop",
                                        id={"type": "stop-btn", **idx},
                                        color="danger",
                                        className="me-1",
                                        disabled=True,
                                    ),
                                    dbc.Button(
                                        "Replay",
                                        id={"type": "replay-btn", **idx},
                                        color="warning",
                                        className="me-1",
                                    ),
                                    dbc.Button(
                                        "Delete",
                                        id={"type": "delete-btn", **idx},
                                        color="dark",
                                    ),
                                ]
                            ),
                        ],
                        width=6,
                        className="d-flex align-items-end",
                    ),
                ],
                className="mb-3",
            ),
            # Progress bar
            html.Div(
                [
                    dbc.Progress(
                        id={"type": "progress-bar", **idx},
                        value=0,
                        label="Idle",
                        className="mb-2",
                    ),
                    html.Div(
                        id={"type": "current-test", **idx},
                        children="Status: idle",
                        className="text-muted small",
                    ),
                ],
                className="p-2 border rounded mb-3",
            ),
            # Console + results
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H6("Console Output"),
                            html.Pre(
                                id={"type": "console-output", **idx},
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
                        ],
                        width=7,
                    ),
                    dbc.Col(
                        [
                            html.H6("Test Results"),
                            html.Div(
                                id={"type": "results-table", **idx},
                                children="No results yet.",
                                style={
                                    "height": "300px",
                                    "overflow": "auto",
                                },
                            ),
                        ],
                        width=5,
                    ),
                ],
            ),
        ],
    )


def create_app_layout() -> html.Div:
    """Build the full application layout with one default session."""
    return html.Div(
        [
            # Header
            dbc.Navbar(
                dbc.Container(
                    [
                        html.H4(
                            "Robot Framework Chat Control Panel",
                            className="text-white mb-0",
                        ),
                        dbc.Button(
                            "+ New Session",
                            id="new-session-btn",
                            color="primary",
                            size="sm",
                            className="ms-auto",
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
                color="dark",
                dark=True,
                className="mb-3",
            ),
            # Main content
            dbc.Container(
                [
                    # Session tabs
                    dbc.Tabs(
                        id="session-tabs",
                        active_tab="tab-0",
                        children=[
                            dbc.Tab(label="Session 1 (0m 0s)", tab_id="tab-0"),
                        ],
                    ),
                    # Container for all session panels (all rendered upfront)
                    html.Div(
                        id="sessions-container",
                        children=[create_session_panel(0)],
                        className="mt-3",
                    ),
                ],
                fluid=True,
                className="px-4",
            ),
            # Polling timer
            dcc.Interval(id="interval-component", interval=500),
            # Single toast container
            html.Div(id="toast-container"),
            # Hidden counter for total sessions created (never decrements)
            dcc.Store(id="session-counter", data=1),
        ]
    )
