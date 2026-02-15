"""Robot Framework listener for archiving test results to SQL database.

Automatically stores test run summaries and individual test results
into the configured database (SQLite or PostgreSQL) after each
top-level suite completes.

Usage:
    robot --listener rfc.db_listener.DbListener results/
    robot --listener rfc.db_listener.DbListener:database_url=postgresql://... results/

The listener reads DATABASE_URL from the environment if no explicit
URL is provided.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from robot.api import logger  # type: ignore

from . import __version__
from .git_metadata import collect_ci_metadata
from .test_database import TestDatabase, TestResult, TestRun


class DbListener:
    """Listener that archives Robot Framework results to a SQL database.

    Usage:
        robot --listener rfc.db_listener.DbListener tests/
        robot --listener rfc.db_listener.DbListener:database_url=<URL> tests/
    """

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self, database_url: Optional[str] = None):
        self._database_url = database_url or os.getenv("DATABASE_URL")
        self._db: Optional[TestDatabase] = None
        self._start_time: Optional[datetime] = None
        self._ci_info: Dict[str, str] = {}
        self._test_cases: List[Dict[str, Any]] = []
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

    def end_test(self, name: str, attributes: Dict[str, Any]) -> None:
        doc = attributes.get("doc", "")
        tags = attributes.get("tags", [])

        score = None
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("score:"):
                try:
                    score = int(tag.split(":")[1])
                except (ValueError, IndexError):
                    pass

        self._test_cases.append(
            {
                "name": name,
                "status": attributes.get("status", "UNKNOWN"),
                "score": score,
                "question": doc if doc else None,
                "message": attributes.get("message", ""),
            }
        )

    def end_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return

        end_time = datetime.utcnow()
        duration = (
            (end_time - self._start_time).total_seconds() if self._start_time else 0.0
        )

        total = int(attributes.get("totaltests", 0))
        pass_count = 0
        fail_count = 0
        skip_count = 0

        for tc in self._test_cases:
            if tc["status"] == "PASS":
                pass_count += 1
            elif tc["status"] == "FAIL":
                fail_count += 1
            else:
                skip_count += 1

        if total == 0:
            total = len(self._test_cases)

        model_name = os.getenv("DEFAULT_MODEL", "unknown")

        run = TestRun(
            timestamp=self._start_time or end_time,
            model_name=model_name,
            model_release_date=self._ci_info.get("Model_Release_Date"),
            model_parameters=self._ci_info.get("Model_Parameters"),
            test_suite=name,
            git_commit=self._ci_info.get("Commit_SHA", ""),
            git_branch=self._ci_info.get("Branch", ""),
            pipeline_url=self._ci_info.get("Pipeline_URL", ""),
            runner_id=self._ci_info.get("Runner_ID", ""),
            runner_tags=self._ci_info.get("Runner_Tags", ""),
            total_tests=total,
            passed=pass_count,
            failed=fail_count,
            skipped=skip_count,
            duration_seconds=duration,
            rfc_version=__version__,
        )

        try:
            db = self._get_db()
            run_id = db.add_test_run(run)

            results = [
                TestResult(
                    run_id=run_id,
                    test_name=tc["name"],
                    test_status=tc["status"],
                    score=tc["score"],
                    question=tc["question"],
                    expected_answer=None,
                    actual_answer=None,
                    grading_reason=None,
                )
                for tc in self._test_cases
            ]
            db.add_test_results(results)

            logger.info(
                f"Archived {len(results)} test results to database (run_id={run_id})"
            )
        except Exception as e:
            logger.warn(f"Failed to archive results to database: {e}")
