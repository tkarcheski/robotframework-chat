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
from robot.api.interfaces import ListenerV3  # type: ignore
from robot.libraries.BuiltIn import BuiltIn  # type: ignore
from robot.result.model import Message  # type: ignore
from robot.result.model import TestCase as ResultTest  # type: ignore
from robot.result.model import TestSuite as ResultSuite  # type: ignore
from robot.running.model import TestCase as RunningTest  # type: ignore
from robot.running.model import TestSuite as RunningSuite  # type: ignore

from . import __version__
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
from .rfc_data import RFC_DATA_PREFIX
from .test_database import (
    TestDatabase,
    TestResult,
    TestRun,
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


class DbListener(ListenerV3):
    """Listener that archives Robot Framework results to a SQL database.

    Captures structured data emitted by keywords via log messages with
    the ``RFC_DATA:`` prefix. Recognised keys:

    - ``RFC_DATA:actual_answer:<text>``
    - ``RFC_DATA:expected_answer:<text>``
    - ``RFC_DATA:grading_reason:<text>``

    At end_suite, stores run-level and test-level summaries.  In close()
    — after Robot has flushed the output file — reads output.xml,
    gzip-compresses it, and updates the database row.

    Usage:
        robot --listener rfc.db_listener.DbListener tests/
        robot --listener rfc.db_listener.DbListener:database_url=<URL> tests/
    """

    ROBOT_LISTENER_API_VERSION = 3

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
        self._last_run_id: Optional[int] = None

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

    def start_suite(self, data: RunningSuite, result: ResultSuite) -> None:
        self._suite_depth += 1
        if self._suite_depth == 1:
            self._start_time = datetime.now(UTC)
            self._ci_info = collect_ci_metadata()
            self._host_info = collect_host_info()
            self._test_cases = []
            dest = self._describe_database_destination()
            banner = f"DbListener: archiving results to {dest}"
            logger.info(banner)
            logger.console(banner)

    def start_test(self, data: RunningTest, result: ResultTest) -> None:
        """Reset per-test structured data at the start of each test."""
        self._current_test_data = {}
        self._current_test_name = data.name

    def log_message(self, message: Message) -> None:
        """Capture structured data from ``RFC_DATA:`` log messages."""
        text = message.message
        if not isinstance(text, str):
            return
        if text.startswith(RFC_DATA_PREFIX):
            payload = text[len(RFC_DATA_PREFIX) :]
            key, _, value = payload.partition(":")
            if key:
                self._current_test_data[key] = value
            return
        # Detect near-miss typos to prevent silent data loss.
        _warn_near_miss(text)

    def end_test(self, data: RunningTest, result: ResultTest) -> None:
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

        parsed = _parse_tags(tags)
        tags_str = parsed["tags_sorted"]

        # Extract performance metrics from llm_metrics JSON
        metrics = _extract_llm_metrics(self._current_test_data.get("llm_metrics"))

        self._test_cases.append(
            {
                "name": data.name,
                "status": result.status,
                "score": score,
                "tags": tags_str,
                "question": doc if doc else "",
                "message": result.message,
                "actual_answer": self._current_test_data.get("actual_answer"),
                "expected_answer": self._current_test_data.get("expected_answer"),
                "grading_reason": self._current_test_data.get("grading_reason"),
                "tag_severity": parsed["tag_severity"],
                "tag_tier": parsed["tag_tier"],
                "tag_verify": parsed["tag_verify"],
                "thinking_text": self._current_test_data.get("thinking_text"),
                "thinking_tokens": _safe_int(
                    self._current_test_data.get("thinking_tokens")
                ),
                "num_ctx": _safe_int(self._current_test_data.get("num_ctx"))
                or metrics.get("num_ctx"),
                "num_predict": _safe_int(self._current_test_data.get("num_predict"))
                or metrics.get("num_predict"),
                "eval_count": metrics.get("eval_count"),
                "eval_duration_ns": metrics.get("eval_duration_ns"),
                "prompt_eval_count": metrics.get("prompt_eval_count"),
                "prompt_eval_duration_ns": metrics.get("prompt_eval_duration_ns"),
                "load_duration_ns": metrics.get("load_duration_ns"),
                "total_duration_ns": metrics.get("total_duration_ns"),
                "tokens_per_second": metrics.get("eval_rate"),
                "reasoning_tokens": metrics.get("reasoning_tokens"),
                "cached_tokens": metrics.get("cached_tokens"),
                "accepted_prediction_tokens": metrics.get("accepted_prediction_tokens"),
                "rejected_prediction_tokens": metrics.get("rejected_prediction_tokens"),
                "token_retry_count": _safe_int(
                    self._current_test_data.get("token_retry_count")
                ),
                "token_retry_max_tokens": _safe_int(
                    self._current_test_data.get("token_retry_max_tokens")
                ),
            }
        )
        self._current_test_data = {}
        self._current_test_name = None

    def end_suite(self, data: RunningSuite, result: ResultSuite) -> None:
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return

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
        output_xml_url = _build_output_xml_url()
        output_xml_source = _build_output_xml_source()

        # Collect inference params from Robot variables or environment
        run_temperature = _get_robot_float("TEMPERATURE")
        run_seed = _get_robot_int("SEED")
        run_top_p = _get_robot_float("TOP_P")
        run_top_k = _get_robot_int("TOP_K")

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
            output_xml_url=output_xml_url,
            output_xml_gz=b"",
            output_xml_source=output_xml_source,
            temperature=run_temperature,
            seed=run_seed,
            top_p=run_top_p,
            top_k=run_top_k,
        )

        try:
            db = self._get_db()
            run_id = db.add_test_run(run)
            self._last_run_id = run_id

            results = [
                TestResult(
                    run_id=run_id,
                    test_name=tc["name"],
                    test_status=tc["status"],
                    score=_nvl(tc.get("score"), -1.0),
                    tags=_nvl(tc.get("tags"), ""),
                    question=_nvl(tc.get("question"), ""),
                    expected_answer=_nvl(tc.get("expected_answer"), ""),
                    actual_answer=_nvl(tc.get("actual_answer"), ""),
                    grading_reason=_nvl(tc.get("grading_reason"), ""),
                    rfc_version=__version__,
                    tag_severity=_nvl(tc.get("tag_severity"), ""),
                    tag_tier=_nvl(tc.get("tag_tier"), -1),
                    tag_verify=_nvl(tc.get("tag_verify"), ""),
                    thinking_text=_nvl(tc.get("thinking_text"), ""),
                    thinking_tokens=_nvl(tc.get("thinking_tokens"), 0),
                    reasoning_tokens=_nvl(tc.get("reasoning_tokens"), 0),
                    cached_tokens=_nvl(tc.get("cached_tokens"), 0),
                    accepted_prediction_tokens=_nvl(
                        tc.get("accepted_prediction_tokens"), 0
                    ),
                    rejected_prediction_tokens=_nvl(
                        tc.get("rejected_prediction_tokens"), 0
                    ),
                    num_ctx=_nvl(tc.get("num_ctx"), 0),
                    num_predict=_nvl(tc.get("num_predict"), 0),
                    eval_count=_nvl(tc.get("eval_count"), 0),
                    eval_duration_ns=_nvl(tc.get("eval_duration_ns"), 0),
                    prompt_eval_count=_nvl(tc.get("prompt_eval_count"), 0),
                    prompt_eval_duration_ns=_nvl(tc.get("prompt_eval_duration_ns"), 0),
                    load_duration_ns=_nvl(tc.get("load_duration_ns"), 0),
                    total_duration_ns=_nvl(tc.get("total_duration_ns"), 0),
                    tokens_per_second=_nvl(tc.get("tokens_per_second"), 0.0),
                    token_retry_count=_nvl(tc.get("token_retry_count"), 0),
                    token_retry_max_tokens=_nvl(tc.get("token_retry_max_tokens"), 0),
                )
                for tc in self._test_cases
            ]
            db.add_test_results(results)

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

        output_xml_gz = read_and_compress_output_xml()
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
