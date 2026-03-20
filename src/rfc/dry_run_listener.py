"""Robot Framework listener for dry-run validation results.

Logs dry-run results to the console. The robot_dry_run_results table
has been dropped in the 2-table schema redesign — dry-run validation
results are now logged only, not persisted to the database.

Usage:
    robot --dryrun --listener rfc.dry_run_listener.DryRunListener robot/
"""

from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from robot.api import logger  # type: ignore

from .base_listener import BaseListener


class DryRunListener(BaseListener):
    """Listener that logs Robot Framework dry-run results."""

    def __init__(self) -> None:
        super().__init__()
        self._start_time: Optional[datetime] = None
        self._test_cases: List[Dict[str, Any]] = []
        self._errors: List[str] = []

    # ------------------------------------------------------------------
    # BaseListener hooks
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        self._start_time = datetime.now(UTC)
        self._test_cases = []
        self._errors = []

    def on_test_end(self, data: Any, result: Any) -> None:
        status = result.status
        self._test_cases.append({"name": data.name, "status": status})
        if status == "FAIL":
            msg = result.message
            if msg:
                self._errors.append(f"{data.name}: {msg}")

    def on_suite_end(self, data: Any, result: Any) -> None:
        total = len(self._test_cases)
        pass_count = sum(1 for tc in self._test_cases if tc["status"] == "PASS")
        fail_count = sum(1 for tc in self._test_cases if tc["status"] == "FAIL")

        summary = (
            f"DryRunListener: {total} tests, {pass_count} passed, {fail_count} failed"
        )
        logger.info(summary)
        logger.console(summary)

        if self._errors:
            for error in self._errors:
                logger.warn(error)
