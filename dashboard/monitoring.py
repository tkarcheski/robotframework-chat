"""Monitoring data collectors and layout builders for Ollama and GitLab.

This module is self-contained: data classes, polling helpers, Dash layout
builders, and Plotly figure generators all live here so the rest of the
dashboard only needs to import high-level functions.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import requests
from dash import dcc, html

from rfc.suite_config import load_config

# ---------------------------------------------------------------------------
# Cream theme constants (must match layout.py)
# ---------------------------------------------------------------------------

_BG = "#FAF3E8"
_CARD_BG = "#FFF8F0"
_BORDER = "#E0D5C5"
_TEXT = "#3E3529"
_MUTED = "#8C7E6A"

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "poll_interval_seconds": 30,
    "history_hours": 24,
    "gitlab_api_url": "",
    "gitlab_project_id": "",
    "gitlab_token_env": "GITLAB_TOKEN",
    "pipeline_count": 20,
}


def _monitoring_config() -> dict:
    """Return the ``monitoring`` section from test_suites.yaml, with defaults."""
    cfg = load_config()
    mon = cfg.get("monitoring", {})
    merged = {**_DEFAULTS, **mon}
    return merged


def _node_list() -> list[dict]:
    """Return the ``nodes`` list from config.

    Priority:
    1. ``OLLAMA_NODES_LIST`` env-var (comma-separated hostnames)
    2. ``nodes`` section in ``config/test_suites.yaml``

    When running inside Docker, ``localhost`` nodes are automatically
    rewritten to ``host.docker.internal`` so the container can reach
    the host machine's Ollama instance.
    """
    env_list = os.environ.get("OLLAMA_NODES_LIST", "")
    if env_list:
        nodes = [
            {"hostname": h.strip(), "port": 11434}
            for h in env_list.split(",")
            if h.strip()
        ]
    else:
        cfg = load_config()
        nodes = list(cfg.get("nodes", []))

    # Inside Docker, localhost refers to the container itself.
    # Rewrite to host.docker.internal so we can reach the host's Ollama.
    if _running_in_docker():
        for node in nodes:
            if node["hostname"] in ("localhost", "127.0.0.1"):
                node["hostname"] = "host.docker.internal"

    return nodes


def _running_in_docker() -> bool:
    """Detect whether the current process is running inside a Docker container."""
    try:
        return Path("/.dockerenv").exists()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# OllamaMonitor -- polls /api/ps on every configured node
# ---------------------------------------------------------------------------


# One data-point in the 24-hour ring buffer
@dataclass
class _OllamaSnapshot:
    ts: datetime
    reachable: bool
    running_models: list[dict] = field(default_factory=list)


class OllamaMonitor:
    """Poll configured Ollama nodes and maintain a 24-hour history."""

    _instance: OllamaMonitor | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        cfg = _monitoring_config()
        self._poll_interval = cfg["poll_interval_seconds"]
        self._history_hours = cfg["history_hours"]
        # Max points = history_hours * 3600 / poll_interval
        max_pts = int(self._history_hours * 3600 / max(self._poll_interval, 1)) + 1

        self._nodes = _node_list()
        # {hostname: deque[_OllamaSnapshot]}
        self._history: dict[str, deque[_OllamaSnapshot]] = {
            n["hostname"]: deque(maxlen=max_pts) for n in self._nodes
        }
        self._last_poll: float = 0

    @classmethod
    def get(cls) -> OllamaMonitor:
        """Return the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # -- Polling -------------------------------------------------------------

    def poll_if_due(self) -> None:
        """Poll all nodes if enough time has elapsed since the last poll."""
        now = time.time()
        if now - self._last_poll < self._poll_interval:
            return
        self._last_poll = now
        self._poll_all()

    def _poll_all(self) -> None:
        for node in self._nodes:
            host = node["hostname"]
            port = node.get("port", 11434)
            url = f"http://{host}:{port}/api/ps"
            snap = _OllamaSnapshot(ts=datetime.now(), reachable=False)
            try:
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    snap.reachable = True
                    snap.running_models = resp.json().get("models", [])
            except Exception:
                pass
            self._history[host].append(snap)

    # -- Data access ---------------------------------------------------------

    def node_names(self) -> list[str]:
        return [n["hostname"] for n in self._nodes]

    def latest(self, hostname: str) -> _OllamaSnapshot | None:
        buf = self._history.get(hostname)
        return buf[-1] if buf else None

    def history(self, hostname: str) -> list[_OllamaSnapshot]:
        return list(self._history.get(hostname, []))


# ---------------------------------------------------------------------------
# PipelineMonitor -- reads GitLab CI pipeline status
# ---------------------------------------------------------------------------


@dataclass
class PipelineInfo:
    id: int
    status: str
    ref: str
    sha: str
    created_at: str
    updated_at: str
    web_url: str
    source: str = ""


class PipelineMonitor:
    """Fetch recent GitLab CI pipeline runs."""

    _instance: PipelineMonitor | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        cfg = _monitoring_config()
        # Env vars override YAML config so docker-compose can inject values
        self._api_url = os.environ.get("GITLAB_API_URL") or cfg["gitlab_api_url"]
        self._project_id = (
            os.environ.get("GITLAB_PROJECT_ID") or cfg["gitlab_project_id"]
        )
        self._token_env = cfg["gitlab_token_env"]
        self._count = cfg["pipeline_count"]
        self._pipelines: list[PipelineInfo] = []
        self._last_poll: float = 0
        self._poll_interval = max(cfg["poll_interval_seconds"], 30)

    @classmethod
    def get(cls) -> PipelineMonitor:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def poll_if_due(self) -> None:
        now = time.time()
        if now - self._last_poll < self._poll_interval:
            return
        self._last_poll = now
        self._fetch()

    def _fetch(self) -> None:
        if not self._api_url or not self._project_id:
            return
        token = os.environ.get(self._token_env, "")
        headers: dict[str, str] = {}
        if token:
            headers["PRIVATE-TOKEN"] = token
        url = (
            f"{self._api_url}/api/v4/projects/{self._project_id}"
            f"/pipelines?per_page={self._count}&order_by=updated_at"
        )
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            self._pipelines = [
                PipelineInfo(
                    id=p["id"],
                    status=p.get("status", "unknown"),
                    ref=p.get("ref", ""),
                    sha=p.get("sha", "")[:8],
                    created_at=p.get("created_at", ""),
                    updated_at=p.get("updated_at", ""),
                    web_url=p.get("web_url", ""),
                    source=p.get("source", ""),
                )
                for p in resp.json()
            ]
        except Exception:
            pass  # keep stale data on transient failures

    @property
    def pipelines(self) -> list[PipelineInfo]:
        return list(self._pipelines)


# ---------------------------------------------------------------------------
# Plotly figure builders
# ---------------------------------------------------------------------------

_STATUS_COLORS = {
    "success": "#27AE60",
    "failed": "#C0392B",
    "running": "#D4A017",
    "pending": "#8C7E6A",
    "canceled": "#A59B8C",
    "skipped": "#C4B8A5",
    "manual": "#2980B9",
    "unknown": "#8C7E6A",
}


def build_pipeline_table(pipelines: list[PipelineInfo]) -> html.Div:
    """Return a table of recent pipeline runs, or configuration help."""
    if not pipelines:
        return html.Div(
            [
                html.H6(
                    "GitLab Pipeline Monitoring Not Configured",
                    style={"color": _TEXT},
                ),
                html.P(
                    "To enable pipeline monitoring, set the following in "
                    "your .env file or environment:",
                    style={"color": _MUTED},
                ),
                html.Pre(
                    "GITLAB_API_URL=https://gitlab.example.com\n"
                    "GITLAB_PROJECT_ID=12345\n"
                    "GITLAB_TOKEN=glpat-xxxxxxxxxxxx",
                    style={
                        "backgroundColor": "#2B2520",
                        "color": "#E8DFD0",
                        "padding": "12px",
                        "borderRadius": "6px",
                        "fontSize": "13px",
                    },
                ),
                html.P(
                    "Or configure in config/test_suites.yaml under "
                    "monitoring.gitlab_api_url and monitoring.gitlab_project_id.",
                    style={"color": _MUTED, "fontSize": "0.9em"},
                ),
            ],
            style={
                "padding": "20px",
                "backgroundColor": _CARD_BG,
                "borderRadius": "8px",
                "border": f"1px solid {_BORDER}",
            },
        )

    header = html.Thead(
        html.Tr(
            [
                html.Th("ID", style={"color": _TEXT}),
                html.Th("Status", style={"color": _TEXT}),
                html.Th("Branch", style={"color": _TEXT}),
                html.Th("SHA", style={"color": _TEXT}),
                html.Th("Source", style={"color": _TEXT}),
                html.Th("Updated", style={"color": _TEXT}),
            ]
        )
    )

    rows = []
    for p in pipelines:
        badge_color = _STATUS_COLORS.get(p.status, "#8C7E6A")
        updated = _short_ts(p.updated_at)
        rows.append(
            html.Tr(
                [
                    html.Td(str(p.id), style={"color": _TEXT}),
                    html.Td(
                        html.Span(
                            p.status,
                            style={
                                "backgroundColor": badge_color,
                                "color": "white",
                                "padding": "2px 8px",
                                "borderRadius": "4px",
                                "fontSize": "0.85em",
                                "fontWeight": "bold",
                            },
                        )
                    ),
                    html.Td(p.ref, style={"color": _TEXT}),
                    html.Td(
                        html.Code(
                            p.sha,
                            style={"color": _TEXT, "backgroundColor": "#E8DFD0"},
                        )
                    ),
                    html.Td(p.source, style={"color": _MUTED}),
                    html.Td(updated, style={"color": _MUTED}),
                ]
            )
        )

    body = html.Tbody(rows)
    return html.Div(
        dbc.Table(
            [header, body],
            bordered=True,
            hover=True,
            responsive=True,
            size="sm",
            style={"backgroundColor": _CARD_BG},
        ),
        style={
            "borderRadius": "8px",
            "overflow": "hidden",
            "border": f"1px solid {_BORDER}",
        },
    )


def build_ollama_cards(monitor: OllamaMonitor) -> list:
    """Return a list of Bootstrap cards, one per Ollama node."""
    cards = []
    for host in monitor.node_names():
        snap = monitor.latest(host)
        if snap is None:
            status_text = "No data"
            badge_color = "secondary"
            model_info = ""
        elif not snap.reachable:
            status_text = "Offline"
            badge_color = "danger"
            model_info = ""
        elif snap.running_models:
            status_text = "Busy"
            badge_color = "warning"
            names = [m.get("name", "?") for m in snap.running_models]
            model_info = ", ".join(names)
        else:
            status_text = "Idle"
            badge_color = "success"
            model_info = ""

        card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div(
                        [
                            html.Strong(host, style={"color": _TEXT}),
                            dbc.Badge(
                                status_text,
                                color=badge_color,
                                className="ms-2",
                            ),
                        ],
                        className="d-flex align-items-center",
                    ),
                    style={"backgroundColor": _CARD_BG},
                ),
                dbc.CardBody(
                    [
                        html.Div(
                            f"Models: {model_info}"
                            if model_info
                            else "No models loaded",
                            className="small mb-2",
                            style={"color": _MUTED},
                        ),
                        dcc.Graph(
                            figure=_build_timeline_fig(monitor, host),
                            config={"displayModeBar": False},
                            style={"height": "120px"},
                        ),
                    ],
                    style={"backgroundColor": _CARD_BG},
                ),
            ],
            className="mb-3",
            style={"border": f"1px solid {_BORDER}", "borderRadius": "8px"},
        )
        cards.append(card)
    return cards


def _build_timeline_fig(monitor: OllamaMonitor, hostname: str) -> go.Figure:
    """Build a 24-hour uptime/busy bar timeline for one host."""
    history = monitor.history(hostname)
    fig = go.Figure()

    if not history:
        fig.update_layout(
            template="plotly_white",
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            height=100,
            paper_bgcolor=_CARD_BG,
            plot_bgcolor=_CARD_BG,
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[
                {
                    "text": "Waiting for data...",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"color": _MUTED},
                }
            ],
        )
        return fig

    now = datetime.now()
    window_start = now - timedelta(hours=24)

    times = []
    colors = []
    hovers = []
    for snap in history:
        if snap.ts < window_start:
            continue
        times.append(snap.ts)
        if not snap.reachable:
            colors.append("#C0392B")  # warm red = offline
            hovers.append("Offline")
        elif snap.running_models:
            colors.append("#D4A017")  # warm gold = busy
            names = ", ".join(m.get("name", "?") for m in snap.running_models)
            hovers.append(f"Busy: {names}")
        else:
            colors.append("#27AE60")  # green = idle
            hovers.append("Idle")

    fig.add_trace(
        go.Bar(
            x=times,
            y=[1] * len(times),
            marker_color=colors,
            hovertext=hovers,
            hoverinfo="text+x",
            width=max(
                monitor._poll_interval * 1000,  # ms
                1000 * 60,  # at least 1 min wide
            ),
        )
    )

    fig.update_layout(
        template="plotly_white",
        margin={"l": 0, "r": 0, "t": 0, "b": 25},
        height=100,
        paper_bgcolor=_CARD_BG,
        plot_bgcolor="#FAF3E8",
        xaxis={
            "range": [window_start, now],
            "tickformat": "%H:%M",
            "dtick": 3600000 * 4,  # 4-hour ticks
            "tickfont": {"color": _MUTED},
        },
        yaxis={"visible": False},
        showlegend=False,
        bargap=0,
    )
    return fig


def _short_ts(iso_str: str) -> str:
    """Convert an ISO timestamp to HH:MM display."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return iso_str[:16]


# ---------------------------------------------------------------------------
# Dash layout sections for each monitoring tab
# ---------------------------------------------------------------------------


def create_pipelines_layout() -> html.Div:
    """Layout for the GitLab Pipelines tab."""
    return html.Div(
        id="pipelines-content",
        children=[
            dbc.Row(
                [
                    dbc.Col(
                        html.H5(
                            "GitLab Pipelines",
                            style={"color": _TEXT, "fontWeight": "600"},
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        html.Span(
                            id="pipelines-last-updated",
                            className="small",
                            style={"color": _MUTED},
                        ),
                        width="auto",
                        className="ms-auto d-flex align-items-center",
                    ),
                ],
                className="mb-3 align-items-center",
            ),
            html.Div(id="pipelines-table", children="Loading..."),
        ],
        className="p-3",
    )


def create_ollama_layout() -> html.Div:
    """Layout for the Ollama Hosts tab."""
    return html.Div(
        id="ollama-content",
        children=[
            dbc.Row(
                [
                    dbc.Col(
                        html.H5(
                            "Ollama Hosts",
                            style={"color": _TEXT, "fontWeight": "600"},
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                dbc.Badge("Idle", color="success", className="me-1"),
                                dbc.Badge("Busy", color="warning", className="me-1"),
                                dbc.Badge("Offline", color="danger"),
                            ]
                        ),
                        width="auto",
                        className="ms-auto",
                    ),
                ],
                className="mb-3 align-items-center",
            ),
            html.Div(id="ollama-cards", children="Loading..."),
        ],
        className="p-3",
    )
