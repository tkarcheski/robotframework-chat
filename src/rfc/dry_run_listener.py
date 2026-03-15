"""Robot Framework listener for dry-run validation results.

Logs dry-run results to the console. The robot_dry_run_results table
has been dropped in the 2-table schema redesign — dry-run validation
results are now logged only, not persisted to the database.

Usage:
    robot --dryrun --listener rfc.dry_run_listener.DryRunListener robot/
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from robot.api import logger  # type: ignore


class DryRunListener:
    """Listener that logs Robot Framework dry-run results."""

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self, database_url: Optional[str] = None):
        self._start_time: Optional[datetime] = None
        self._test_cases: List[Dict[str, Any]] = []
        self._errors: List[str] = []
        self._suite_depth = 0

    def start_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth += 1
        if self._suite_depth == 1:
            self._start_time = datetime.utcnow()
            self._test_cases = []
            self._errors = []

    def end_test(self, name: str, attributes: Dict[str, Any]) -> None:
        status = attributes.get("status", "UNKNOWN")
        self._test_cases.append({"name": name, "status": status})
        if status == "FAIL":
            msg = attributes.get("message", "")
            if msg:
                self._errors.append(f"{name}: {msg}")

    def end_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return

        total = int(attributes.get("totaltests", 0))
        pass_count = sum(1 for tc in self._test_cases if tc["status"] == "PASS")
        fail_count = sum(1 for tc in self._test_cases if tc["status"] == "FAIL")

        if total == 0:
            total = len(self._test_cases)

        summary = (
            f"DryRunListener: {total} tests, {pass_count} passed, {fail_count} failed"
        )
        logger.info(summary)
        logger.console(summary)

        if self._errors:
            for error in self._errors:
                logger.warn(error)
