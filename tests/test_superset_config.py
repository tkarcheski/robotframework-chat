"""Tests for the Superset theme configuration in superset/superset_config.py.

The config module lives outside src/rfc/ (it is mounted into the Superset
container at runtime), so we add the superset/ directory to sys.path and
import it directly, mirroring tests/test_bootstrap_dashboards.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SUPERSET_DIR = str(Path(__file__).resolve().parent.parent / "superset")
if _SUPERSET_DIR not in sys.path:
    sys.path.insert(0, _SUPERSET_DIR)

import superset_config  # noqa: E402


def test_default_theme_is_dark() -> None:
    """Dark mode loads by default for everyone (THEME_DEFAULT)."""
    assert superset_config.THEME_DEFAULT["algorithm"] == "dark"


def test_light_theme_reachable_via_toggle() -> None:
    """A light theme stays available, so users can toggle away from dark."""
    assert superset_config.THEME_DARK is not None
    assert superset_config.THEME_DARK["algorithm"] == "default"


def test_dark_theme_uses_tron_palette() -> None:
    """The dark theme carries the TRON cyan + near-black palette."""
    token = superset_config.THEME_DEFAULT["token"]
    assert token["colorPrimary"] == "#00dffc"
    assert token["colorBgBase"] == "#0a0a0f"


def test_ui_theme_administration_enabled() -> None:
    """Admins can manage system-wide themes from the Superset UI."""
    assert superset_config.ENABLE_UI_THEME_ADMINISTRATION is True
