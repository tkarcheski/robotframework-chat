"""Robot Framework listener for archiving dry-run validation results.

Stores dry-run results in the robot_dry_run_results table, separate from
real test execution data. Useful for quickly validating test syntax and
keyword availability, and tracking validation health over time.

Usage:
    robot --dryrun --listener rfc.dry_run_listener.DryRunListener robot/
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from robot.api import logger  # type: ignore

from . import __version__
from .git_metadata import collect_ci_metadata
from .test_database import DryRunResult, TestDatabase


class DryRunListener:
    """Listener that archives Robot Framework dry-run results to a SQL database."""

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self, database_url: Optional[str] = None):
        self._database_url = database_url or os.getenv("DATABASE_URL")
        self._db: Optional[TestDatabase] = None
        self._start_time: Optional[datetime] = None
        self._ci_info: Dict[str, str] = {}
        self._test_cases: List[Dict[str, Any]] = []
        self._errors: List[str] = []
        self._suite_depth = 0

    def _get_db(self) -> TestDatabase:
        if self._db is None:
            if self._database_url:
                self._db = TestDatabase(database_url=self._database_url)
            else:
                self._db = TestDatabase()
        return self._db

    def start_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth += 1
        if self._suite_depth == 1:
            self._start_time = datetime.utcnow()
            self._ci_info = collect_ci_metadata()
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

        end_time = datetime.utcnow()
        duration = (
            (end_time - self._start_time).total_seconds() if self._start_time else 0.0
        )

        total = int(attributes.get("totaltests", 0))
        pass_count = sum(1 for tc in self._test_cases if tc["status"] == "PASS")
        fail_count = sum(1 for tc in self._test_cases if tc["status"] == "FAIL")
        skip_count = sum(
            1 for tc in self._test_cases if tc["status"] not in ("PASS", "FAIL")
        )

        if total == 0:
            total = len(self._test_cases)

        result = DryRunResult(
            timestamp=self._start_time or end_time,
            test_suite=name,
            total_tests=total,
            passed=pass_count,
            failed=fail_count,
            skipped=skip_count,
            duration_seconds=duration,
            git_commit=self._ci_info.get("Commit_SHA", ""),
            git_branch=self._ci_info.get("Branch", ""),
            rfc_version=__version__,
            errors="\n".join(self._errors) if self._errors else None,
        )

        try:
            db = self._get_db()
            row_id = db.add_dry_run_result(result)
            logger.info(
                f"Archived dry-run result to database (id={row_id}): "
                f"{total} tests, {pass_count} passed, {fail_count} failed"
            )
        except Exception as e:
            logger.warn(f"Failed to archive dry-run result to database: {e}")
