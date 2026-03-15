"""Robot Framework listener for archiving test results to SQL database.

Stores test run summaries, individual test results, and a gzip-compressed
copy of output.xml into the configured database (SQLite or PostgreSQL)
after each top-level suite completes.

Captures LLM answer and grading data via structured log messages
emitted by keywords using the ``RFC_DATA:`` prefix convention.

Usage:
    robot --listener rfc.db_listener.DbListener results/
    robot --listener rfc.db_listener.DbListener:database_url=postgresql://... results/

The listener reads DATABASE_URL from the environment if no explicit
URL is provided.
"""

import gzip
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from robot.api import logger  # type: ignore
from robot.libraries.BuiltIn import BuiltIn  # type: ignore

from . import __version__
from .git_metadata import collect_ci_metadata
from .host_info import collect_host_info
from .test_database import (
    TestDatabase,
    TestResult,
    TestRun,
)

# Prefix used by keywords to emit structured data for the listener.
RFC_DATA_PREFIX = "RFC_DATA:"


def _parse_tags(tags: list[str]) -> Dict[str, Any]:
    """Parse structured tag prefixes and sort remaining tags.

    Extracts ``severity:<val>``, ``tier:<int>``, and ``verify:<val>`` into
    dedicated fields.  Remaining tags are sorted alphabetically and joined
    with commas.  The structured prefixes are removed from the remaining
    tag string to avoid duplication.

    Args:
        tags: List of tag strings from Robot Framework test attributes.

    Returns:
        Dict with keys ``tag_severity``, ``tag_tier``, ``tag_verify``,
        and ``tags_sorted`` (comma-separated remaining tags or None).
    """
    severity: Optional[str] = None
    tier: Optional[int] = None
    verify: Optional[str] = None
    other: list[str] = []
    for tag in sorted(tags):
        if tag.startswith("severity:"):
            severity = tag.split(":", 1)[1]
        elif tag.startswith("tier:"):
            try:
                tier = int(tag.split(":", 1)[1])
            except ValueError:
                other.append(tag)
        elif tag.startswith("verify:"):
            verify = tag.split(":", 1)[1]
        else:
            other.append(tag)
    return {
        "tag_severity": severity,
        "tag_tier": tier,
        "tag_verify": verify,
        "tags_sorted": ",".join(other) if other else None,
    }


class DbListener:
    """Listener that archives Robot Framework results to a SQL database.

    Captures structured data emitted by keywords via log messages with
    the ``RFC_DATA:`` prefix. Recognised keys:

    - ``RFC_DATA:actual_answer:<text>``
    - ``RFC_DATA:expected_answer:<text>``
    - ``RFC_DATA:grading_reason:<text>``

    At end_suite, reads output.xml, gzip-compresses it, and stores the
    blob alongside run-level and test-level summaries.

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
        self._host_info: Dict[str, Any] = {}
        self._test_cases: List[Dict[str, Any]] = []
        self._suite_depth = 0
        # Per-test structured data captured from RFC_DATA: log messages.
        self._current_test_data: Dict[str, str] = {}
        self._current_test_name: Optional[str] = None

    def _get_db(self) -> TestDatabase:
        if self._db is None:
            if self._database_url:
                self._db = TestDatabase(database_url=self._database_url)
            else:
                self._db = TestDatabase()
        return self._db

    def _describe_database_destination(self) -> str:
        """Return a human-readable description of the database target.

        Does NOT trigger lazy database initialization.
        """
        url = self._database_url
        if url and url.startswith("postgresql"):
            parsed = urlparse(url)
            host_part = parsed.hostname or "localhost"
            if parsed.port:
                host_part += f":{parsed.port}"
            db_name = parsed.path.lstrip("/") if parsed.path else ""
            return f"PostgreSQL: {host_part}/{db_name}"
        if url and url.startswith("sqlite:///"):
            path = url.replace("sqlite:///", "")
            return f"SQLite: {path}"
        return "NOT CONFIGURED (DATABASE_URL is not set)"

    def start_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth += 1
        if self._suite_depth == 1:
            self._start_time = datetime.utcnow()
            self._ci_info = collect_ci_metadata()
            self._host_info = collect_host_info()
            self._test_cases = []
            dest = self._describe_database_destination()
            banner = f"DbListener: archiving results to {dest}"
            logger.info(banner)
            logger.console(banner)

    def start_test(self, name: str, attributes: Dict[str, Any]) -> None:
        """Reset per-test structured data at the start of each test."""
        self._current_test_data = {}
        self._current_test_name = name

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

        if score is None:
            rfc_score = self._current_test_data.get("score")
            if rfc_score is not None:
                try:
                    score = int(rfc_score)
                except (ValueError, TypeError):
                    pass

        parsed = _parse_tags(tags)
        tags_str = parsed["tags_sorted"]

        self._test_cases.append(
            {
                "name": name,
                "status": attributes.get("status", "UNKNOWN"),
                "score": score,
                "tags": tags_str,
                "question": doc if doc else None,
                "message": attributes.get("message", ""),
                "actual_answer": self._current_test_data.get("actual_answer"),
                "expected_answer": self._current_test_data.get("expected_answer"),
                "grading_reason": self._current_test_data.get("grading_reason"),
                "tag_severity": parsed["tag_severity"],
                "tag_tier": parsed["tag_tier"],
                "tag_verify": parsed["tag_verify"],
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

        # Prefer the Robot variable (set via --variable DEFAULT_MODEL:<model>)
        # over env-var / CI metadata.
        robot_model: Optional[str] = None
        try:
            robot_model = BuiltIn().get_variable_value("${DEFAULT_MODEL}")
        except Exception:
            pass  # Not running inside Robot context (e.g. unit tests)

        model_name: str = (
            robot_model
            or self._ci_info.get("Default_Model")
            or os.getenv("DEFAULT_MODEL")
            or "unknown"
        )

        hostname = self._host_info.get("hostname")

        # Read and gzip output.xml
        output_xml_gz = _read_and_compress_output_xml()
        output_xml_url = _build_output_xml_url()
        output_xml_source = _build_output_xml_source()

        run = TestRun(
            timestamp=self._start_time or end_time,
            model_name=model_name,
            test_suite=name,
            total_tests=total,
            passed=pass_count,
            failed=fail_count,
            skipped=skip_count,
            duration_seconds=duration,
            git_commit=self._ci_info.get("Commit_SHA", ""),
            git_branch=self._ci_info.get("Branch", ""),
            hostname=hostname,
            rfc_version=__version__,
            output_xml_url=output_xml_url,
            output_xml_gz=output_xml_gz,
            output_xml_source=output_xml_source,
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
                    tags=tc.get("tags"),
                    question=tc["question"],
                    expected_answer=tc.get("expected_answer"),
                    actual_answer=tc.get("actual_answer"),
                    grading_reason=tc.get("grading_reason"),
                    rfc_version=__version__,
                    tag_severity=tc.get("tag_severity"),
                    tag_tier=tc.get("tag_tier"),
                    tag_verify=tc.get("tag_verify"),
                )
                for tc in self._test_cases
            ]
            db.add_test_results(results)

            dest = self._describe_database_destination()
            blob_size = _format_size(len(output_xml_gz)) if output_xml_gz else "none"
            summary = (
                f"DbListener: archived {len(results)} test result(s) "
                f"+ output.xml ({blob_size}) "
                f"to {dest} (run_id={run_id})"
            )
            logger.info(summary)
            logger.console(summary)
        except Exception as e:
            error_msg = f"DbListener: FAILED to archive results: {e}"
            logger.warn(error_msg)
            logger.console(error_msg)


def _read_and_compress_output_xml() -> Optional[bytes]:
    """Read output.xml from Robot's output directory and gzip-compress it."""
    output_dir = os.getenv("ROBOT_OUTPUT_DIR")
    if not output_dir:
        return None
    output_xml = os.path.join(output_dir, "output.xml")
    if not os.path.isfile(output_xml):
        return None
    try:
        with open(output_xml, "rb") as f:
            return gzip.compress(f.read())
    except OSError:
        return None


def _build_output_xml_source() -> Optional[str]:
    """Return the filesystem path to the Robot Framework output.xml.

    This traces the test run back to the original output.xml that was
    produced by Robot Framework, enabling audit and replay.
    """
    output_dir = os.getenv("ROBOT_OUTPUT_DIR")
    if output_dir:
        candidate = os.path.join(output_dir, "output.xml")
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
        return candidate
    return None


def _build_output_xml_url() -> Optional[str]:
    """Build a URL to the output.xml file from environment variables.

    Priority:
    1. REPORT_BASE_URL — explicit base URL
    2. CI_JOB_URL — GitLab CI artifact URL pattern
    3. ROBOT_OUTPUT_DIR — local file path fallback
    """
    base = os.getenv("REPORT_BASE_URL")
    if base:
        return f"{base.rstrip('/')}/output.xml"

    ci_job_url = os.getenv("CI_JOB_URL")
    if ci_job_url:
        return f"{ci_job_url}/artifacts/browse/output.xml"

    output_dir = os.getenv("ROBOT_OUTPUT_DIR")
    if output_dir:
        return f"{output_dir.rstrip('/')}/output.xml"

    return None


def _format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
