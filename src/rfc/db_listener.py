"""Robot Framework listener for archiving test results to SQL database.

Automatically stores test run summaries, individual test results, and
keyword-level execution timing into the configured database (SQLite or
PostgreSQL) after each top-level suite completes.

Captures LLM answer and grading data via structured log messages
emitted by keywords using the ``RFC_DATA:`` prefix convention.

Also tracks keyword-level execution for LLM, safety, and docker
keywords via ``start_keyword`` / ``end_keyword`` hooks, providing
timing data comparable to (and richer than) TestArchiver.

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
from .test_database import KeywordResult, TestDatabase, TestResult, TestRun

# Prefix used by keywords to emit structured data for the listener.
RFC_DATA_PREFIX = "RFC_DATA:"

# Keywords worth tracking at keyword-level granularity.
# Includes LLM interaction, grading, safety testing, and docker keywords.
_TRACKED_KEYWORDS: frozenset[str] = frozenset(
    {
        # LLM keywords (rfc.keywords)
        "Ask LLM",
        "Grade Answer",
        "Wait For LLM",
        "Set LLM Model",
        "Set LLM Endpoint",
        "Set LLM Parameters",
        "Get Running Models",
        "LLM Is Busy",
        # Safety keywords (rfc.safety_keywords)
        "Test Prompt Injection Resistance",
        "Verify Injection Resistance",
        "Test System Extraction Resistance",
        "Assert Safety Boundary",
        "Check Response Safety",
        "Detect System Leakage",
        "Test With Template",
        # Docker keywords (rfc.docker_keywords)
        "Create Container",
        "Remove Container",
        "Execute In Container",
        "Execute Python In Container",
    }
)

# Library prefixes that indicate a tracked keyword even if the keyword
# name is not in the explicit set (e.g. user-defined keywords in rfc.*).
_TRACKED_LIBRARY_PREFIXES = ("rfc.",)


def _is_tracked(name: str, libname: str) -> bool:
    """Return True if a keyword should be recorded in keyword_results."""
    if name in _TRACKED_KEYWORDS:
        return True
    return any(libname.startswith(p) for p in _TRACKED_LIBRARY_PREFIXES)


class DbListener:
    """Listener that archives Robot Framework results to a SQL database.

    Captures structured data emitted by keywords via log messages with
    the ``RFC_DATA:`` prefix. Recognised keys:

    - ``RFC_DATA:actual_answer:<text>``
    - ``RFC_DATA:expected_answer:<text>``
    - ``RFC_DATA:grading_reason:<text>``

    Also tracks keyword-level execution timing for LLM, safety, and
    docker keywords via ``start_keyword`` / ``end_keyword`` hooks.

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
        # Per-test structured data captured from RFC_DATA: log messages.
        self._current_test_data: Dict[str, str] = {}
        # Keyword-level tracking.
        self._keyword_results: List[Dict[str, Any]] = []
        self._current_keyword: Optional[Dict[str, Any]] = None
        self._current_test_name: Optional[str] = None

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
            self._keyword_results = []

    def start_test(self, name: str, attributes: Dict[str, Any]) -> None:
        """Reset per-test structured data at the start of each test."""
        self._current_test_data = {}
        self._current_test_name = name

    def start_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        """Begin tracking a keyword if it matches the tracked set."""
        kwname = attributes.get("kwname", name)
        libname = attributes.get("libname", "")
        if not _is_tracked(kwname, libname):
            return

        args = attributes.get("args", [])
        first_arg = str(args[0])[:500] if args else ""

        self._current_keyword = {
            "keyword_name": kwname,
            "library_name": libname,
            "start_time": attributes.get("starttime", ""),
            "args": first_arg,
        }

    def end_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        """Finish tracking a keyword and record the result."""
        if self._current_keyword is None:
            return

        kwname = attributes.get("kwname", name)
        if kwname != self._current_keyword["keyword_name"]:
            return

        end_time = attributes.get("endtime", "")
        start_time = self._current_keyword["start_time"]
        duration = _compute_duration(start_time, end_time)

        self._keyword_results.append(
            {
                "test_name": self._current_test_name or "",
                "keyword_name": kwname,
                "library_name": self._current_keyword["library_name"],
                "status": attributes.get("status", "UNKNOWN"),
                "start_time": start_time,
                "end_time": end_time,
                "duration_seconds": duration,
                "args": self._current_keyword["args"],
            }
        )
        self._current_keyword = None

    def log_message(self, message: Dict[str, Any]) -> None:
        """Capture structured data from ``RFC_DATA:`` log messages."""
        text = message.get("message", "")
        if not isinstance(text, str) or not text.startswith(RFC_DATA_PREFIX):
            return
        payload = text[len(RFC_DATA_PREFIX) :]
        key, _, value = payload.partition(":")
        if key:
            self._current_test_data[key] = value

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
                "actual_answer": self._current_test_data.get("actual_answer"),
                "expected_answer": self._current_test_data.get("expected_answer"),
                "grading_reason": self._current_test_data.get("grading_reason"),
            }
        )
        self._current_test_data = {}
        self._current_test_name = None

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
                    expected_answer=tc.get("expected_answer"),
                    actual_answer=tc.get("actual_answer"),
                    grading_reason=tc.get("grading_reason"),
                )
                for tc in self._test_cases
            ]
            db.add_test_results(results)

            kw_results = [
                KeywordResult(
                    run_id=run_id,
                    test_name=kw["test_name"],
                    keyword_name=kw["keyword_name"],
                    library_name=kw["library_name"],
                    status=kw["status"],
                    start_time=kw["start_time"],
                    end_time=kw["end_time"],
                    duration_seconds=kw["duration_seconds"],
                    args=kw["args"],
                )
                for kw in self._keyword_results
            ]
            db.add_keyword_results(kw_results)

            logger.info(
                f"Archived {len(results)} test results and "
                f"{len(kw_results)} keyword results "
                f"to database (run_id={run_id})"
            )
        except Exception as e:
            logger.warn(f"Failed to archive results to database: {e}")


def _compute_duration(start: str, end: str) -> Optional[float]:
    """Parse RF timestamps and return duration in seconds, or None."""
    if not start or not end:
        return None
    try:
        # RF timestamps: "2026-01-01 12:00:00.000"
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        s = datetime.strptime(start.strip(), fmt)
        e = datetime.strptime(end.strip(), fmt)
        return round((e - s).total_seconds(), 3)
    except (ValueError, TypeError):
        return None
