"""Layout builder functions for the dashboard. Pure HTML, no callbacks.

All test-suite, IQ-level, and container-profile options are loaded from
``config/test_suites.yaml`` via :mod:`rfc.suite_config` so that the
dashboard, CI pipeline, and Makefile share a single source of truth.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.core.docker_network import resolve_node_hostname
from dashboard.core.llm_registry import llm_registry
from dashboard.monitoring import create_ollama_layout, create_pipelines_layout
from rfc.suite_config import (
    default_iq_levels,
    default_model,
    default_profile,
    iq_dropdown_options,
    node_dropdown_options,
    profile_dropdown_options,
    suite_dropdown_options,
)

# -- Dark theme colour constants ----------------------------------------------

_BG = "#1a1a2e"  # page background (deep navy)
_CARD_BG = "#16213e"  # card / panel background (dark blue)
_HEADER_BG = "#0f3460"  # navbar (medium blue)
_BORDER = "#2a2a4a"  # subtle border
_TEXT = "#e0e0e0"  # primary text (light gray)
_MUTED = "#8892a0"  # muted / secondary text
_CONSOLE_BG = "#0d1117"  # console (near black)
_CONSOLE_TEXT = "#c9d1d9"  # console text (GitHub-style light)
_ACCENT = "#e94560"  # accent colour for highlights

# Dropdown styling for dark theme
_DROPDOWN_STYLE = {
    "backgroundColor": "#1e2a3a",
    "color": _TEXT,
    "border": f"1px solid {_BORDER}",
    "borderRadius": "6px",
}


def _node_options() -> list[dict[str, str]]:
    """Build Docker-aware Ollama Host dropdown options.

    Applies hostname rewriting for Docker bridge networking so the
    dropdown values are usable from inside the container.
    """
    raw_options = node_dropdown_options()
    result = []
    for opt in raw_options:
        # opt["value"] is "hostname:port"
        parts = opt["value"].split(":", 1)
        hostname = parts[0]
        port = parts[1] if len(parts) > 1 else "11434"
        resolved = resolve_node_hostname(hostname)
        new_value = f"{resolved}:{port}"
        result.append({"label": opt["label"], "value": new_value})
    return result


def _model_options() -> list[dict]:
    """Get LLM model options from all Ollama nodes, with availability info."""
    all_models = llm_registry.get_all_models()
    if all_models:
        return all_models
    fallback = default_model()
    return [{"label": fallback, "value": fallback}]


def create_session_panel(index: int) -> html.Div:
    """Create a complete session panel for the given index.

    Each component ID is a dict like {"type": "suite-dropdown", "index": 0}.
    """
    idx = {"index": index}

    return html.Div(
        id={"type": "session-panel", **idx},
        style={
            "display": "block" if index == 0 else "none",
            "backgroundColor": _CARD_BG,
            "padding": "16px",
            "borderRadius": "8px",
            "border": f"1px solid {_BORDER}",
        },
        children=[
            # Settings row 1: dropdowns
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label(
                                "Test Suite",
                                style={"color": _TEXT, "fontWeight": "600"},
                            ),
                            dcc.Dropdown(
                                id={"type": "suite-dropdown", **idx},
                                options=suite_dropdown_options(),
                                value="robot",
                                clearable=False,
                                style=_DROPDOWN_STYLE,
                            ),
                        ],
                        width=3,
                    ),
                    dbc.Col(
                        [
                            dbc.Label(
                                "IQ Levels (Tags)",
                                style={"color": _TEXT, "fontWeight": "600"},
                            ),
                            dcc.Dropdown(
                                id={"type": "iq-dropdown", **idx},
                                options=iq_dropdown_options(),
                                value=default_iq_levels(),
                                multi=True,
                                style=_DROPDOWN_STYLE,
                            ),
                        ],
                        width=3,
                    ),
                    dbc.Col(
                        [
                            dbc.Label(
                                "Ollama Host",
                                style={"color": _TEXT, "fontWeight": "600"},
                            ),
                            dcc.Dropdown(
                                id={"type": "host-dropdown", **idx},
                                options=(host_opts := _node_options()),
                                value=host_opts[0]["value"]
                                if host_opts
                                else "localhost:11434",
                                clearable=False,
                                style=_DROPDOWN_STYLE,
                            ),
                        ],
                        width=3,
                    ),
                    dbc.Col(
                        [
                            dbc.Label(
                                "LLM Model",
                                style={"color": _TEXT, "fontWeight": "600"},
                            ),
                            dcc.Dropdown(
                                id={"type": "model-dropdown", **idx},
                                options=_model_options(),
                                value=default_model(),
                                clearable=False,
                                style=_DROPDOWN_STYLE,
                            ),
                        ],
                        width=3,
                    ),
                ],
                className="mb-3",
            ),
            # Settings row 2: profile, switches, buttons
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label(
                                "Container Profile",
                                style={"color": _TEXT, "fontWeight": "600"},
                            ),
                            dcc.Dropdown(
                                id={"type": "profile-dropdown", **idx},
                                options=profile_dropdown_options(),
                                value=default_profile(),
                                clearable=False,
                                style=_DROPDOWN_STYLE,
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
                                style={"color": _TEXT},
                            ),
                            dbc.Checklist(
                                options=[{"label": " Dry run", "value": True}],
                                value=[],
                                id={"type": "dry-run-check", **idx},
                                switch=True,
                                style={"color": _TEXT},
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
                                        outline=True,
                                        color="dark",
                                    ),
                                ]
                            ),
                            dbc.Button(
                                "Upload to DB",
                                id={"type": "upload-btn", **idx},
                                color="info",
                                className="ms-3",
                                disabled=True,
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
                        color="info",
                        style={"backgroundColor": "#2a2a4a"},
                    ),
                    html.Div(
                        id={"type": "current-test", **idx},
                        children="Status: idle",
                        className="small",
                        style={"color": _MUTED},
                    ),
                ],
                className="p-2 rounded mb-3",
                style={
                    "border": f"1px solid {_BORDER}",
                    "backgroundColor": _BG,
                },
            ),
            # Console + results
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H6(
                                "Console Output",
                                style={"color": _TEXT, "fontWeight": "600"},
                            ),
                            html.Pre(
                                id={"type": "console-output", **idx},
                                children="",
                                style={
                                    "height": "300px",
                                    "overflow": "auto",
                                    "backgroundColor": _CONSOLE_BG,
                                    "color": _CONSOLE_TEXT,
                                    "padding": "10px",
                                    "fontFamily": "monospace",
                                    "fontSize": "12px",
                                    "border": f"1px solid {_BORDER}",
                                    "borderRadius": "6px",
                                },
                            ),
                        ],
                        width=7,
                    ),
                    dbc.Col(
                        [
                            html.H6(
                                "Test Results",
                                style={"color": _TEXT, "fontWeight": "600"},
                            ),
                            html.Div(
                                id={"type": "results-table", **idx},
                                children="No results yet.",
                                style={
                                    "height": "300px",
                                    "overflow": "auto",
                                    "color": _MUTED,
                                },
                            ),
                        ],
                        width=5,
                    ),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Top-level application layout with tabbed navigation
# ---------------------------------------------------------------------------


def _sessions_section() -> html.Div:
    """The existing session management UI (tabs + panels)."""
    return html.Div(
        [
            dbc.Row(
                dbc.Col(
                    dbc.Button(
                        "+ New Session",
                        id="new-session-btn",
                        color="primary",
                        size="sm",
                    ),
                    className="d-flex justify-content-end mb-2",
                ),
            ),
            dbc.Tabs(
                id="session-tabs",
                active_tab="tab-0",
                children=[
                    dbc.Tab(label="Session 1 (0m 0s)", tab_id="tab-0"),
                ],
            ),
            html.Div(
                id="sessions-container",
                children=[create_session_panel(0)],
                className="mt-3",
            ),
        ]
    )


def create_app_layout() -> html.Div:
    """Build the full application layout with top-level tab navigation."""
    return html.Div(
        style={"backgroundColor": _BG, "minHeight": "100vh", "color": _TEXT},
        children=[
            # Header
            dbc.Navbar(
                dbc.Container(
                    [
                        html.H4(
                            "Robot Framework Chat Control Panel",
                            className="mb-0",
                            style={"color": "#FFF8F0"},
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
                style={"backgroundColor": _HEADER_BG},
                dark=True,
                className="mb-3",
            ),
            # Top-level navigation tabs
            dbc.Container(
                [
                    dbc.Tabs(
                        id="top-tabs",
                        active_tab="top-sessions",
                        children=[
                            dbc.Tab(label="Sessions", tab_id="top-sessions"),
                            dbc.Tab(label="Ollama Hosts", tab_id="top-ollama"),
                            dbc.Tab(label="GitLab Pipelines", tab_id="top-pipelines"),
                        ],
                        className="mb-3",
                    ),
                    # Tab content panels (all rendered; visibility toggled)
                    html.Div(
                        id="top-tab-sessions",
                        children=_sessions_section(),
                        style={"display": "block"},
                    ),
                    html.Div(
                        id="top-tab-ollama",
                        children=create_ollama_layout(),
                        style={"display": "none"},
                    ),
                    html.Div(
                        id="top-tab-pipelines",
                        children=create_pipelines_layout(),
                        style={"display": "none"},
                    ),
                ],
                fluid=True,
                className="px-4",
            ),
            # Polling timers
            dcc.Interval(id="interval-component", interval=500),
            dcc.Interval(id="monitoring-interval", interval=30_000),
            # Single toast container
            html.Div(id="toast-container"),
            # Hidden counter for total sessions created (never decrements)
            dcc.Store(id="session-counter", data=1),
        ],
    )
