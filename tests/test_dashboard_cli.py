"""Tests for dashboard.cli."""

import sys
from unittest.mock import MagicMock, patch


class TestDashboardCli:
    def _run_main(self, host="0.0.0.0", port=8050, debug=False):
        """Run CLI main() with a mocked app and parse_args."""
        mock_app = MagicMock()
        mock_module = MagicMock()
        mock_module.app = mock_app

        with (
            patch.dict(sys.modules, {"dashboard.app": mock_module}),
            patch(
                "argparse.ArgumentParser.parse_args",
                return_value=MagicMock(host=host, port=port, debug=debug),
            ),
        ):
            from dashboard.cli import main

            main()

        return mock_app

    def test_default_args(self):
        mock_app = self._run_main()
        mock_app.run.assert_called_once_with(
            debug=False, host="0.0.0.0", port=8050
        )

    def test_custom_host_and_port(self):
        mock_app = self._run_main(host="127.0.0.1", port=9000)
        mock_app.run.assert_called_once_with(
            debug=False, host="127.0.0.1", port=9000
        )

    def test_debug_flag(self):
        mock_app = self._run_main(debug=True)
        mock_app.run.assert_called_once_with(
            debug=True, host="0.0.0.0", port=8050
        )
