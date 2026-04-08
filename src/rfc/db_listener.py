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

import os
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from robot.api import logger  # type: ignore
from robot.libraries.BuiltIn import BuiltIn  # type: ignore

from . import __version__
from .base_listener import BaseListener
from .git_metadata import collect_ci_metadata
from .host_info import collect_host_info
from .metrics import (
    extract_llm_metrics,
    get_robot_float,
    get_robot_int,
    nvl,
    parse_tags,
    safe_int,
    warn_near_miss,
)
from .output_xml import (
    build_output_xml_source,
    build_output_xml_url,
    format_size,
    read_and_compress_output_xml,
    resolve_output_dir,
    resolve_output_file,
)
from .test_database import (
    TestDatabase,
    TestResult,
    TestRun,
    TestRunArtifact,
    build_result_artifacts,
)

# Backward-compatible aliases (these names are imported by tests).
_nvl = nvl
_parse_tags = parse_tags
_safe_int = safe_int
_extract_llm_metrics = extract_llm_metrics
_warn_near_miss = warn_near_miss
_get_robot_float = get_robot_float
_get_robot_int = get_robot_int

# Backward-compatible aliases for output_xml functions.
_resolve_output_dir = resolve_output_dir
_resolve_output_file = resolve_output_file
_read_and_compress_output_xml = read_and_compress_output_xml
_build_output_xml_source = build_output_xml_source
_build_output_xml_url = build_output_xml_url
_format_size = format_size


class DbListener(BaseListener):
    """Listener that archives Robot Framework results to a SQL database.

    Extends :class:`~rfc.base_listener.BaseListener` for suite depth
    tracking and RFC_DATA capture.  Recognised keys:

    - ``RFC_DATA:actual_answer:<text>``
    - ``RFC_DATA:expected_answer:<text>``
    - ``RFC_DATA:grading_reason:<text>``
    - ``RFC_DATA:llm_metrics:<json>``
    - ``RFC_DATA:score:<float>``
    - ``RFC_DATA:thinking_text:<text>``
    - ``RFC_DATA:thinking_tokens:<int>``

    At end_suite, stores run-level and test-level summaries.  In close()
    — after Robot has flushed the output file — reads output.xml,
    gzip-compresses it, and updates the database row.

    Usage:
        robot --listener rfc.db_listener.DbListener tests/
        robot --listener rfc.db_listener.DbListener:database_url=<URL> tests/
    """

    def __init__(self, database_url: Optional[str] = None):
        super().__init__()
        self._database_url = database_url or os.getenv("DATABASE_URL")
        self._db: Optional[TestDatabase] = None
        self._start_time: Optional[datetime] = None
        self._ci_info: Dict[str, str] = {}
        self._host_info: Dict[str, Any] = {}
        self._test_cases: List[Dict[str, Any]] = []
        self._current_test_name: Optional[str] = None
        self._last_run_id: Optional[int] = None
        self._resolved_output_path: str = ""

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # BaseListener hooks
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        self._start_time = datetime.now(UTC)
        self._ci_info = collect_ci_metadata()
        self._host_info = collect_host_info()
        self._test_cases = []
        dest = self._describe_database_destination()
        banner = f"DbListener: archiving results to {dest}"
        logger.info(banner)
        logger.console(banner)

    def on_test_start(self, data: Any, result: Any) -> None:
        self._current_test_name = data.name

    def on_log_message(self, message: Any) -> None:
        """Detect near-miss typos to prevent silent data loss."""
        warn_near_miss(message.message)

    def on_test_end(self, data: Any, result: Any) -> None:
        doc = data.doc
        tags = list(data.tags)

        score: float = -1.0
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("score:"):
                try:
                    score = float(tag.split(":")[1])
                except (ValueError, IndexError):
                    pass

        if score == -1.0:
            rfc_score = self._current_test_data.get("score")
            if rfc_score is not None:
                try:
                    score = float(rfc_score)
                except (ValueError, TypeError):
                    pass

        parsed = parse_tags(tags)
        tags_str = parsed["tags_sorted"]

        metrics = extract_llm_metrics(self._current_test_data.get("llm_metrics"))

        self._test_cases.append(
            {
                "name": data.name,
                "status": result.status,
                "score": score,
                "tags": tags_str,
                "message": result.message,
                "tag_severity": parsed["tag_severity"],
                "tag_tier": parsed["tag_tier"],
                "tag_verify": parsed["tag_verify"],
                "eval_count": metrics.get("eval_count"),
                "thinking_tokens": safe_int(
                    self._current_test_data.get("thinking_tokens")
                ),
                # Archive fields — written to test_result_artifacts after
                # the per-result primary key is known.
                "question": doc if doc else "",
                "actual_answer": self._current_test_data.get("actual_answer"),
                "expected_answer": self._current_test_data.get("expected_answer"),
                "grading_reason": self._current_test_data.get("grading_reason"),
                "thinking_text": self._current_test_data.get("thinking_text"),
            }
        )
        self._current_test_name = None

    def on_suite_end(self, data: Any, result: Any) -> None:
        end_time = datetime.now(UTC)
        duration = (
            (end_time - self._start_time).total_seconds() if self._start_time else 0.0
        )

        total = result.statistics.total
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

        hostname = self._host_info.get("hostname", "")

        # output.xml is read later in close(), after Robot flushes the file.
        # Resolve the path now while Robot context is still available.
        output_xml_source = build_output_xml_source()
        self._resolved_output_path = resolve_output_file()

        run = TestRun(
            timestamp=self._start_time or end_time,
            model_name=model_name,
            test_suite=data.name,
            total_tests=total,
            passed=pass_count,
            failed=fail_count,
            skipped=skip_count,
            duration_seconds=duration,
            git_commit=self._ci_info.get("Commit_SHA", ""),
            git_branch=self._ci_info.get("Branch", ""),
            hostname=hostname,
            rfc_version=__version__,
        )

        try:
            db = self._get_db()
            run_id = db.add_test_run(run)
            self._last_run_id = run_id

            # Record the source path immediately so Superset drill-down can
            # show where the XML lives even before close() compresses it.
            if output_xml_source:
                db.add_test_run_artifact(
                    TestRunArtifact(
                        run_id=run_id,
                        output_xml_source=output_xml_source,
                    )
                )

            results = [
                TestResult(
                    run_id=run_id,
                    test_name=tc["name"],
                    test_status=tc["status"],
                    score=nvl(tc.get("score"), -1.0),
                    tags=nvl(tc.get("tags"), ""),
                    tag_severity=nvl(tc.get("tag_severity"), ""),
                    tag_tier=nvl(tc.get("tag_tier"), -1),
                    tag_verify=nvl(tc.get("tag_verify"), ""),
                    eval_count=nvl(tc.get("eval_count"), 0),
                    thinking_tokens=nvl(tc.get("thinking_tokens"), 0),
                )
                for tc in self._test_cases
            ]
            db.add_test_results(results)

            artifacts = build_result_artifacts(
                self._test_cases, db.get_result_ids_for_run(run_id)
            )
            if artifacts:
                db.add_test_result_artifacts(artifacts)

            dest = self._describe_database_destination()
            summary = (
                f"DbListener: archived {len(results)} test result(s) "
                f"to {dest} (run_id={run_id}), "
                f"output.xml will be captured in close()"
            )
            logger.info(summary)
            logger.console(summary)
        except Exception as e:
            error_msg = f"DbListener: FAILED to archive results: {e}"
            logger.warn(error_msg)
            logger.console(error_msg)

    def close(self) -> None:
        """Read output.xml after Robot has flushed it and update the DB row.

        Robot Framework calls ``close()`` after all loggers — including
        the output-file writer — have finalised.  This guarantees the
        file is complete, unlike ``end_suite()`` which fires before the
        flush.
        """
        if self._last_run_id is None:
            return

        # Use the path resolved in on_suite_end() while Robot context was
        # still active.  BuiltIn() is no longer available in close().
        output_path = self._resolved_output_path
        if output_path and os.path.isfile(output_path):
            try:
                import gzip

                with open(output_path, "rb") as f:
                    output_xml_gz = gzip.compress(f.read())
            except OSError:
                output_xml_gz = b""
        else:
            output_xml_gz = b""
        if not output_xml_gz:
            return

        try:
            db = self._get_db()
            db.update_output_xml(self._last_run_id, output_xml_gz)
            blob_size = format_size(len(output_xml_gz))
            msg = (
                f"DbListener: updated output.xml ({blob_size}) "
                f"for run_id={self._last_run_id}"
            )
            logger.info(msg)
            logger.console(msg)
        except Exception as e:
            error_msg = (
                f"DbListener: FAILED to update output.xml "
                f"for run_id={self._last_run_id}: {e}"
            )
            logger.warn(error_msg)
            logger.console(error_msg)
