"""Docker networking utilities for hostname resolution.

When the dashboard runs inside a Docker container with bridge networking,
``localhost`` refers to the container itself, not the host machine.  This
module provides helpers to detect the runtime environment and rewrite
hostnames so that Ollama nodes on the host (or LAN) remain reachable.

With ``network_mode: host`` (the recommended Docker setup), these helpers
are effectively no-ops because ``localhost`` already refers to the host.
"""

from __future__ import annotations

import logging
import socket
from functools import lru_cache
from pathlib import Path

_log = logging.getLogger(__name__)

_LOCALHOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


@lru_cache(maxsize=1)
def running_in_docker() -> bool:
    """Detect whether the current process is running inside a Docker container."""
    try:
        return Path("/.dockerenv").exists()
    except Exception:
        return False


@lru_cache(maxsize=1)
def _host_docker_internal_resolves() -> bool:
    """Check whether ``host.docker.internal`` resolves to an IP address.

    Returns ``True`` only when running in Docker **and** the special hostname
    resolves (i.e. the ``extra_hosts`` mapping or Docker Desktop's built-in
    resolution is available).  This avoids blindly rewriting hostnames when
    the container uses ``network_mode: host``, where ``localhost`` already
    points to the host machine.
    """
    if not running_in_docker():
        return False
    try:
        socket.getaddrinfo("host.docker.internal", None)
        return True
    except socket.gaierror:
        return False


def resolve_node_hostname(hostname: str) -> str:
    """Rewrite a localhost-like hostname for Docker bridge networking.

    If the process is running inside Docker with bridge networking (where
    ``host.docker.internal`` resolves), localhost variants are rewritten.
    Otherwise the hostname is returned unchanged.

    This is safe to call unconditionally: under ``network_mode: host`` or
    outside Docker, it is a no-op.
    """
    if hostname in _LOCALHOST_NAMES and _host_docker_internal_resolves():
        _log.debug("Rewriting '%s' -> 'host.docker.internal'", hostname)
        return "host.docker.internal"
    return hostname


def docker_aware_nodes(raw_nodes: list[dict]) -> list[dict]:
    """Return a copy of *raw_nodes* with hostnames resolved for Docker.

    Each dict is expected to have at least ``hostname`` and ``port`` keys.
    The returned list is a shallow copy; original dicts are not mutated.
    """
    result = []
    for node in raw_nodes:
        resolved = resolve_node_hostname(node["hostname"])
        if resolved != node["hostname"]:
            node_copy = dict(node)
            node_copy["hostname"] = resolved
            result.append(node_copy)
        else:
            result.append(node)
    return result
