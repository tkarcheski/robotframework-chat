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
from robot.api.interfaces import ListenerV3  # type: ignore
from robot.result.model import TestCase as ResultTest  # type: ignore
from robot.result.model import TestSuite as ResultSuite  # type: ignore
from robot.running.model import TestCase as RunningTest  # type: ignore
from robot.running.model import TestSuite as RunningSuite  # type: ignore


class DryRunListener(ListenerV3):
    """Listener that logs Robot Framework dry-run results."""

    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self, database_url: Optional[str] = None):
        self._start_time: Optional[datetime] = None
        self._test_cases: List[Dict[str, Any]] = []
        self._errors: List[str] = []
        self._suite_depth = 0

    def start_suite(self, data: RunningSuite, result: ResultSuite) -> None:
        self._suite_depth += 1
        if self._suite_depth == 1:
            self._start_time = datetime.now(UTC)
            self._test_cases = []
            self._errors = []

    def end_test(self, data: RunningTest, result: ResultTest) -> None:
        status = result.status
        self._test_cases.append({"name": data.name, "status": status})
        if status == "FAIL":
            msg = result.message
            if msg:
                self._errors.append(f"{data.name}: {msg}")

    def end_suite(self, data: RunningSuite, result: ResultSuite) -> None:
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return

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
