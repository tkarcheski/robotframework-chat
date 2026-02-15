"""Loader for config/test_suites.yaml -- the single source of truth.

Used by the Dash dashboard and by CI pipeline generation scripts.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def _find_config_path() -> Path:
    """Locate test_suites.yaml relative to this package or cwd."""
    # src/rfc/suite_config.py -> ../../config/test_suites.yaml
    pkg_root = Path(__file__).resolve().parent.parent.parent
    candidate = pkg_root / "config" / "test_suites.yaml"
    if candidate.exists():
        return candidate

    cwd_candidate = Path.cwd() / "config" / "test_suites.yaml"
    if cwd_candidate.exists():
        return cwd_candidate

    raise FileNotFoundError(
        f"Cannot find config/test_suites.yaml in {pkg_root} or {Path.cwd()}"
    )


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Load and cache the test-suite configuration."""
    path = _find_config_path()
    with open(path) as f:
        return yaml.safe_load(f)


# -- Convenience accessors ---------------------------------------------------


def defaults() -> dict[str, Any]:
    """Return the ``defaults`` section."""
    return load_config().get("defaults", {})


def test_suites() -> dict[str, dict[str, Any]]:
    """Return the ``test_suites`` mapping (suite-id -> definition)."""
    return load_config().get("test_suites", {})


def run_all_entry() -> dict[str, Any]:
    """Return the ``run_all`` entry."""
    return load_config().get(
        "run_all", {"label": "Run All Test Suites", "path": "robot"}
    )


def iq_levels() -> list[str]:
    """Return the list of IQ level values."""
    return load_config().get("iq_levels", ["100", "110", "120"])


def container_profiles() -> dict[str, dict[str, Any]]:
    """Return the ``container_profiles`` mapping."""
    return load_config().get("container_profiles", {})


def nodes() -> list[dict[str, Any]]:
    """Return the ``nodes`` list."""
    return load_config().get("nodes", [])


def master_models() -> list[str]:
    """Return the ``master_models`` list of known model names."""
    return load_config().get("master_models", [])


def ci_config() -> dict[str, Any]:
    """Return the ``ci`` section."""
    return load_config().get("ci", {})


# -- Helpers for the dashboard ------------------------------------------------


def suite_dropdown_options() -> list[dict[str, str]]:
    """Build the Dash dropdown options list for test suites.

    Returns a list like ``[{"label": "Run All...", "value": "robot"}, ...]``.
    """
    run_all = run_all_entry()
    options: list[dict[str, str]] = [
        {"label": run_all["label"], "value": run_all["path"]},
    ]
    for _sid, info in test_suites().items():
        options.append({"label": info["label"], "value": info["path"]})
    return options


def iq_dropdown_options() -> list[dict[str, str]]:
    """Build the Dash dropdown options list for IQ levels."""
    return [{"label": f"IQ:{v}", "value": v} for v in iq_levels()]


def profile_dropdown_options() -> list[dict[str, str]]:
    """Build the Dash dropdown options list for container profiles."""
    profiles = container_profiles()
    return [{"label": info["label"], "value": pid} for pid, info in profiles.items()]


def node_dropdown_options() -> list[dict[str, str]]:
    """Build the Dash dropdown options list for Ollama nodes.

    Each option value is ``hostname:port`` for easy URL construction.
    """
    node_list = nodes()
    if not node_list:
        return [{"label": "localhost:11434", "value": "localhost:11434"}]
    return [
        {
            "label": f"{n['hostname']}:{n.get('port', 11434)}",
            "value": f"{n['hostname']}:{n.get('port', 11434)}",
        }
        for n in node_list
    ]


def default_model() -> str:
    return defaults().get("model", "llama3")


def default_iq_levels() -> list[str]:
    return defaults().get("iq_levels", ["100", "110", "120"])


def default_profile() -> str:
    return defaults().get("profile", "STANDARD")
