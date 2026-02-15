"""Tests for dashboard layout builder functions."""

from dash import html

from dashboard.layout import (
    _BG,
    _CARD_BG,
    _TEXT,
    create_app_layout,
    create_session_panel,
)


class TestThemeConstants:
    """Verify dark theme colour constants are consistent."""

    def test_background_is_dark(self):
        # Dark theme should have a dark background (low brightness)
        assert _BG.startswith("#")
        r, g, b = int(_BG[1:3], 16), int(_BG[3:5], 16), int(_BG[5:7], 16)
        brightness = (r + g + b) / 3
        assert brightness < 80, f"Background {_BG} is too bright for a dark theme"

    def test_text_is_light(self):
        assert _TEXT.startswith("#")
        r, g, b = int(_TEXT[1:3], 16), int(_TEXT[3:5], 16), int(_TEXT[5:7], 16)
        brightness = (r + g + b) / 3
        assert brightness > 150, f"Text {_TEXT} is too dark for a dark theme"

    def test_card_bg_darker_than_text(self):
        r1 = int(_CARD_BG[1:3], 16) + int(_CARD_BG[3:5], 16) + int(_CARD_BG[5:7], 16)
        r2 = int(_TEXT[1:3], 16) + int(_TEXT[3:5], 16) + int(_TEXT[5:7], 16)
        assert r1 < r2, "Card background should be darker than text in dark theme"


class TestCreateSessionPanel:
    """Tests for session panel creation."""

    def test_creates_panel_at_index_0(self):
        panel = create_session_panel(0)
        assert isinstance(panel, html.Div)
        assert panel.id == {"type": "session-panel", "index": 0}

    def test_first_panel_visible(self):
        panel = create_session_panel(0)
        assert panel.style["display"] == "block"

    def test_subsequent_panels_hidden(self):
        panel = create_session_panel(1)
        assert panel.style["display"] == "none"

    def test_panel_has_required_children(self):
        panel = create_session_panel(0)
        # Should have children (dropdowns, buttons, console, etc.)
        assert panel.children is not None
        assert len(panel.children) > 0


class TestCreateAppLayout:
    """Tests for the full application layout."""

    def test_returns_div(self):
        layout = create_app_layout()
        assert isinstance(layout, html.Div)

    def test_has_dark_background(self):
        layout = create_app_layout()
        assert layout.style["backgroundColor"] == _BG
        assert layout.style["minHeight"] == "100vh"

    def test_has_navbar(self):
        layout = create_app_layout()
        # First child should be the navbar
        children = layout.children
        assert children is not None
        assert len(children) > 0

    def test_has_interval_components(self):
        layout = create_app_layout()
        # Should contain interval components for polling
        children_types = [type(c).__name__ for c in layout.children]
        assert "Interval" in children_types or any(
            hasattr(c, "id") and getattr(c, "id", "") in ("interval-component", "monitoring-interval")
            for c in layout.children
        )
