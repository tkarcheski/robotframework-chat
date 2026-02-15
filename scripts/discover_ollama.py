#!/usr/bin/env python3
"""Discover Ollama service providers on the network.

Discovery sources (checked in order):

1. ``OLLAMA_NODES`` env-var  -- comma-separated ``host:port`` entries
2. ``OLLAMA_SUBNET`` env-var -- CIDR notation, e.g. ``192.168.1.0/24``
3. Localhost fallback        -- ``localhost:11434``

For each reachable node the script queries ``/api/tags`` and returns a
list of ``{"endpoint": ..., "models": [...]}`` dicts.

Can be used standalone::

    python scripts/discover_ollama.py              # JSON to stdout
    python scripts/discover_ollama.py --pretty      # human-readable

Or imported::

    from scripts.discover_ollama import discover_nodes
    nodes = discover_nodes()
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

DEFAULT_PORT = 11434
CONNECT_TIMEOUT = 2  # seconds
REQUEST_TIMEOUT = 5  # seconds
MAX_SCAN_WORKERS = 64


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _probe_port(host: str, port: int, timeout: float = CONNECT_TIMEOUT) -> bool:
    """Return True if *host:port* accepts a TCP connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _query_models(endpoint: str) -> list[str]:
    """Query an Ollama endpoint and return a list of model names."""
    url = f"{endpoint}/api/tags"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _normalise_endpoint(host: str, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# Discovery strategies
# ---------------------------------------------------------------------------


def _from_env_nodes() -> list[str]:
    """Parse ``OLLAMA_NODES`` into a list of ``http://host:port`` strings."""
    raw = os.environ.get("OLLAMA_NODES", "")
    if not raw.strip():
        return []
    endpoints: list[str] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "://" in entry:
            endpoints.append(entry.rstrip("/"))
        elif ":" in entry:
            host, port = entry.rsplit(":", 1)
            endpoints.append(_normalise_endpoint(host, int(port)))
        else:
            endpoints.append(_normalise_endpoint(entry))
    return endpoints


def _from_subnet() -> list[str]:
    """Scan ``OLLAMA_SUBNET`` for hosts with port 11434 open."""
    subnet_str = os.environ.get("OLLAMA_SUBNET", "")
    if not subnet_str.strip():
        return []

    try:
        network = ipaddress.ip_network(subnet_str.strip(), strict=False)
    except ValueError:
        print(f"Warning: invalid OLLAMA_SUBNET '{subnet_str}'", file=sys.stderr)
        return []

    hosts = list(network.hosts())
    if len(hosts) > 1024:
        print(
            f"Warning: subnet {subnet_str} has {len(hosts)} hosts, "
            "limiting scan to first 1024",
            file=sys.stderr,
        )
        hosts = hosts[:1024]

    reachable: list[str] = []

    def _check(ip: object) -> str | None:
        if _probe_port(str(ip), DEFAULT_PORT):
            return _normalise_endpoint(str(ip))
        return None

    with ThreadPoolExecutor(max_workers=MAX_SCAN_WORKERS) as pool:
        futures = {pool.submit(_check, ip): ip for ip in hosts}
        for future in as_completed(futures):
            result = future.result()
            if result:
                reachable.append(result)

    return sorted(reachable)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_nodes() -> list[dict[str, Any]]:
    """Discover Ollama nodes and their available models.

    Returns a list of dicts::

        [
            {"endpoint": "http://192.168.1.10:11434", "models": ["llama3", "mistral"]},
            ...
        ]
    """
    # Collect candidate endpoints
    endpoints = _from_env_nodes() or _from_subnet()
    if not endpoints:
        endpoints = [_normalise_endpoint("localhost")]

    # Query each endpoint for models (in parallel)
    nodes: list[dict[str, Any]] = []

    def _fetch(ep: str) -> dict[str, Any] | None:
        models = _query_models(ep)
        if models:
            return {"endpoint": ep, "models": models}
        return None

    with ThreadPoolExecutor(max_workers=min(len(endpoints), MAX_SCAN_WORKERS)) as pool:
        futures = {pool.submit(_fetch, ep): ep for ep in endpoints}
        for future in as_completed(futures):
            result = future.result()
            if result:
                nodes.append(result)

    return sorted(nodes, key=lambda n: n["endpoint"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover Ollama nodes on the network")
    parser.add_argument("--pretty", action="store_true", help="Human-readable output")
    args = parser.parse_args()

    nodes = discover_nodes()

    if args.pretty:
        if not nodes:
            print("No Ollama nodes found.")
            return
        for node in nodes:
            print(f"\n  {node['endpoint']}")
            for model in node["models"]:
                print(f"    - {model}")
        print()
    else:
        json.dump(nodes, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
