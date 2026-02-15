"""Monitoring data collectors and layout builders for Ollama and GitLab.

This module is self-contained: data classes, polling helpers, Dash layout
builders, and Plotly figure generators all live here so the rest of the
dashboard only needs to import high-level functions.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import requests
from dash import dcc, html

from dashboard.core.docker_network import docker_aware_nodes
from rfc.suite_config import load_config

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dark theme constants (must match layout.py)
# ---------------------------------------------------------------------------

_BG = "#1a1a2e"
_CARD_BG = "#16213e"
_BORDER = "#2a2a4a"
_TEXT = "#e0e0e0"
_MUTED = "#8892a0"

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

    # When running in Docker with bridge networking, rewrite localhost
    # to host.docker.internal.  Under host networking this is a no-op.
    return docker_aware_nodes(nodes)


# ---------------------------------------------------------------------------
# OllamaMonitor -- polls /api/ps on every configured node
# ---------------------------------------------------------------------------


# One data-point in the 24-hour ring buffer
@dataclass
class _OllamaSnapshot:
    ts: datetime
    reachable: bool
    running_models: list[dict] = field(default_factory=list)
    error: str = ""  # diagnostic info when unreachable


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
        # Perform the first poll immediately in a background thread so the
        # dashboard has data before the first monitoring-interval callback.
        t = threading.Thread(target=self._poll_all, daemon=True)
        t.start()

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

    def force_poll(self) -> None:
        """Force an immediate poll regardless of the interval."""
        self._last_poll = time.time()
        self._poll_all()

    def _poll_all(self) -> None:
        self._last_poll = time.time()
        for node in self._nodes:
            host = node["hostname"]
            port = node.get("port", 11434)
            snap = _OllamaSnapshot(ts=datetime.now(), reachable=False)

            # Try /api/tags first (available in all Ollama versions), then
            # /api/ps for running-model info.  This two-step approach avoids
            # marking a host as offline just because /api/ps is not supported.
            base_url = f"http://{host}:{port}"
            try:
                # Health check via /api/tags
                resp = requests.get(f"{base_url}/api/tags", timeout=5)
                if resp.status_code == 200:
                    snap.reachable = True
                    # Now try to get running models from /api/ps
                    try:
                        ps_resp = requests.get(f"{base_url}/api/ps", timeout=3)
                        if ps_resp.status_code == 200:
                            snap.running_models = ps_resp.json().get("models", [])
                    except Exception:
                        pass  # /api/ps may not exist, host is still reachable
                else:
                    snap.error = f"HTTP {resp.status_code}"
            except requests.exceptions.ConnectionError as e:
                snap.error = f"Connection refused ({host}:{port})"
                if "Name or service not known" in str(e) or "getaddrinfo" in str(e):
                    snap.error = f"DNS lookup failed for '{host}'"
            except requests.exceptions.Timeout:
                snap.error = f"Timeout after 5s ({host}:{port})"
            except Exception as e:
                snap.error = str(e)[:80]
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


def _detect_gitlab_from_git_remote() -> tuple[str, str]:
    """Try to detect GitLab API URL and project path from git remote.

    Returns (api_url, project_path) or ("", "") if detection fails.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return "", ""
        remote = result.stdout.strip()
    except Exception:
        return "", ""

    # SSH: git@gitlab.example.com:group/project.git
    ssh_match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", remote)
    if ssh_match:
        host = ssh_match.group(1)
        path = ssh_match.group(2)
        return f"https://{host}", path

    # HTTPS: https://gitlab.example.com/group/project.git
    https_match = re.match(r"https?://(?:[^@]+@)?([^/]+)/(.+?)(?:\.git)?$", remote)
    if https_match:
        host = https_match.group(1)
        path = https_match.group(2)
        # Skip proxy / localhost remotes (e.g. 127.0.0.1 from Claude Code)
        if host.startswith("127.") or host == "localhost":
            return "", ""
        # Strip /git/ prefix if present (some proxies add it)
        path = re.sub(r"^git/", "", path)
        return f"https://{host}", path

    return "", ""


class PipelineMonitor:
    """Fetch recent GitLab CI pipeline runs.

    Detection priority for GitLab settings:
    1. ``CI_API_V4_URL`` / ``CI_PROJECT_ID`` env vars (inside GitLab CI)
    2. ``GITLAB_API_URL`` / ``GITLAB_PROJECT_ID`` env vars
    3. YAML config ``monitoring.gitlab_api_url`` / ``monitoring.gitlab_project_id``
    4. Auto-detect from git remote URL (resolves project path -> numeric ID)
    """

    _instance: PipelineMonitor | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        cfg = _monitoring_config()
        self._token_env = cfg["gitlab_token_env"]
        self._count = cfg["pipeline_count"]
        self._pipelines: list[PipelineInfo] = []
        self._last_poll: float = 0
        self._poll_interval = max(cfg["poll_interval_seconds"], 30)
        self._fetch_error: str = ""

        # Resolve API URL and project ID from multiple sources
        self._api_url, self._project_id = self._resolve_gitlab_settings(cfg)
        if self._api_url and self._project_id:
            _log.info(
                "GitLab monitoring: %s (project %s)", self._api_url, self._project_id
            )
        else:
            _log.warning("GitLab monitoring not configured")

    def _resolve_gitlab_settings(self, cfg: dict) -> tuple[str, str]:
        """Resolve GitLab API URL and project ID from env/config/git."""
        # 1. GitLab CI environment variables (highest priority)
        ci_api = os.environ.get("CI_API_V4_URL", "")
        ci_pid = os.environ.get("CI_PROJECT_ID", "")
        if ci_api and ci_pid:
            # CI_API_V4_URL is like https://gitlab.example.com/api/v4
            # Strip the /api/v4 suffix to get the base URL
            api_url = ci_api.rsplit("/api/v4", 1)[0]
            return api_url, ci_pid

        # 2. Explicit env vars
        api_url = os.environ.get("GITLAB_API_URL", "") or cfg.get("gitlab_api_url", "")
        project_id = os.environ.get("GITLAB_PROJECT_ID", "") or cfg.get(
            "gitlab_project_id", ""
        )
        if api_url and project_id:
            return api_url.rstrip("/"), str(project_id)

        # 3. Auto-detect from git remote
        remote_url, project_path = _detect_gitlab_from_git_remote()
        if remote_url and project_path:
            # If we have an explicit API URL but no project ID, use the remote
            # to resolve the project path to a numeric ID.
            final_url = api_url or remote_url
            # Try to resolve the project path to a numeric ID via the API
            resolved_id = self._resolve_project_id(final_url, project_path)
            if resolved_id:
                return final_url.rstrip("/"), resolved_id

        return api_url.rstrip("/") if api_url else "", str(
            project_id
        ) if project_id else ""

    def _resolve_project_id(self, api_url: str, project_path: str) -> str:
        """Resolve a project path (group/project) to a numeric GitLab ID."""
        token = os.environ.get(self._token_env, "")
        headers: dict[str, str] = {}
        if token:
            headers["PRIVATE-TOKEN"] = token
        encoded = quote_plus(project_path)
        url = f"{api_url}/api/v4/projects/{encoded}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return str(resp.json()["id"])
        except Exception:
            pass
        return ""

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
            self._fetch_error = "Not configured"
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
            self._fetch_error = ""
        except requests.exceptions.ConnectionError:
            self._fetch_error = f"Cannot connect to {self._api_url}"
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            if code == 401:
                self._fetch_error = "Authentication failed (check GITLAB_TOKEN)"
            elif code == 404:
                self._fetch_error = f"Project {self._project_id} not found"
            else:
                self._fetch_error = f"HTTP {code} from GitLab API"
        except Exception as e:
            self._fetch_error = str(e)[:100]

    @property
    def pipelines(self) -> list[PipelineInfo]:
        return list(self._pipelines)

    @property
    def fetch_error(self) -> str:
        return self._fetch_error

    @property
    def is_configured(self) -> bool:
        return bool(self._api_url and self._project_id)


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


def build_pipeline_table(
    pipelines: list[PipelineInfo],
    monitor: PipelineMonitor | None = None,
) -> html.Div:
    """Return a table of recent pipeline runs, or configuration help."""
    if not pipelines:
        # Show different help depending on whether GitLab is configured
        children: list = []

        if monitor and monitor.is_configured and monitor.fetch_error:
            # Configured but failing
            children.extend(
                [
                    html.H6(
                        "GitLab Pipeline Error",
                        style={"color": "#e94560"},
                    ),
                    html.P(
                        monitor.fetch_error,
                        style={
                            "color": "#e94560",
                            "fontFamily": "monospace",
                            "fontSize": "0.9em",
                        },
                    ),
                ]
            )
        else:
            children.append(
                html.H6(
                    "GitLab Pipeline Monitoring Not Configured",
                    style={"color": _TEXT},
                )
            )

        children.extend(
            [
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
                        "backgroundColor": "#0d1117",
                        "color": "#c9d1d9",
                        "padding": "12px",
                        "borderRadius": "6px",
                        "fontSize": "13px",
                    },
                ),
                html.P(
                    [
                        "Auto-detection: the dashboard will also check ",
                        html.Code("CI_API_V4_URL"),
                        " / ",
                        html.Code("CI_PROJECT_ID"),
                        " (GitLab CI env) and the git remote URL.",
                    ],
                    style={"color": _MUTED, "fontSize": "0.9em"},
                ),
            ]
        )

        return html.Div(
            children,
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
                            style={"color": "#c9d1d9", "backgroundColor": "#0d1117"},
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
            status_text = "Polling..."
            badge_color = "secondary"
            model_info = ""
            error_info = ""
        elif not snap.reachable:
            status_text = "Offline"
            badge_color = "danger"
            model_info = ""
            error_info = snap.error
        elif snap.running_models:
            status_text = "Busy"
            badge_color = "warning"
            names = [m.get("name", "?") for m in snap.running_models]
            model_info = ", ".join(names)
            error_info = ""
        else:
            status_text = "Idle"
            badge_color = "success"
            model_info = ""
            error_info = ""

        body_children = []
        if model_info:
            body_children.append(
                html.Div(
                    f"Running: {model_info}",
                    className="small mb-2",
                    style={"color": _TEXT},
                )
            )
        elif error_info:
            body_children.append(
                html.Div(
                    error_info,
                    className="small mb-2",
                    style={"color": "#e94560", "fontFamily": "monospace"},
                )
            )
        else:
            body_children.append(
                html.Div(
                    "No models running" if snap and snap.reachable else "No data yet",
                    className="small mb-2",
                    style={"color": _MUTED},
                )
            )

        body_children.append(
            dcc.Graph(
                figure=_build_timeline_fig(monitor, host),
                config={"displayModeBar": False},
                style={"height": "120px"},
            )
        )

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
                    body_children,
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
        plot_bgcolor="#1a1a2e",
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
