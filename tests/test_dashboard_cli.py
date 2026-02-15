"""Tests for dashboard.cli."""

from unittest.mock import MagicMock, patch

import pytest


class TestDashboardCli:
    @patch("argparse.ArgumentParser.parse_args")
    @patch("dashboard.app.app")
    def test_default_args(self, mock_app, mock_parse):
        from dashboard.cli import main

        mock_parse.return_value = MagicMock(
            host="0.0.0.0", port=8050, debug=False
        )
        main()
        mock_app.run.assert_called_once_with(
            debug=False, host="0.0.0.0", port=8050
        )

    @patch("argparse.ArgumentParser.parse_args")
    @patch("dashboard.app.app")
    def test_custom_host_and_port(self, mock_app, mock_parse):
        from dashboard.cli import main

        mock_parse.return_value = MagicMock(
            host="127.0.0.1", port=9000, debug=False
        )
        main()
        mock_app.run.assert_called_once_with(
            debug=False, host="127.0.0.1", port=9000
        )

    @patch("argparse.ArgumentParser.parse_args")
    @patch("dashboard.app.app")
    def test_debug_flag(self, mock_app, mock_parse):
        from dashboard.cli import main

        mock_parse.return_value = MagicMock(
            host="0.0.0.0", port=8050, debug=True
        )
        main()
        mock_app.run.assert_called_once_with(
            debug=True, host="0.0.0.0", port=8050
        )
