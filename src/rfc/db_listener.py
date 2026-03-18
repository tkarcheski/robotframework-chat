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
import json
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
from .test_database import (
    TestDatabase,
    TestResult,
    TestRun,
)

# Prefix used by keywords to emit structured data for the listener.
RFC_DATA_PREFIX = "RFC_DATA:"

T = Any  # type alias for _nvl generic usage


def _nvl(value: Any, default: T) -> T:
    """Return *default* when *value* is ``None`` (SQL NVL / COALESCE).

    Unlike ``dict.get(key, default)``, this replaces an explicit ``None``
    value — not just a missing key.
    """
    return default if value is None else value


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
    severity: str = ""
    tier: int = -1
    verify: str = ""
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
        "tags_sorted": ",".join(other) if other else "",
    }


class DbListener(ListenerV3):
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
        if not isinstance(text, str) or not text.startswith(RFC_DATA_PREFIX):
            return
        payload = text[len(RFC_DATA_PREFIX) :]
        key, _, value = payload.partition(":")
        if key:
            self._current_test_data[key] = value

    def end_test(self, data: RunningTest, result: ResultTest) -> None:
        doc = data.doc
        tags = list(data.tags)

        score = -1
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("score:"):
                try:
                    score = int(tag.split(":")[1])
                except (ValueError, IndexError):
                    pass

        if score == -1:
            rfc_score = self._current_test_data.get("score")
            if rfc_score is not None:
                try:
                    score = int(rfc_score)
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
                "accepted_prediction_tokens": metrics.get(
                    "accepted_prediction_tokens"
                ),
                "rejected_prediction_tokens": metrics.get(
                    "rejected_prediction_tokens"
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

        # Read and gzip output.xml
        output_xml_gz = _read_and_compress_output_xml()
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
            output_xml_gz=output_xml_gz,
            output_xml_source=output_xml_source,
            temperature=run_temperature,
            seed=run_seed,
            top_p=run_top_p,
            top_k=run_top_k,
        )

        try:
            db = self._get_db()
            run_id = db.add_test_run(run)

            results = [
                TestResult(
                    run_id=run_id,
                    test_name=tc["name"],
                    test_status=tc["status"],
                    score=_nvl(tc.get("score"), -1),
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


def _resolve_output_dir() -> str:
    """Resolve the Robot Framework output directory.

    Priority:
    1. ``ROBOT_OUTPUT_DIR`` environment variable (explicit override).
    2. Robot Framework's ``${OUTPUT DIR}`` built-in variable.
    3. Empty string if neither is available.
    """
    env_dir = os.getenv("ROBOT_OUTPUT_DIR")
    if env_dir:
        return env_dir
    try:
        robot_dir = BuiltIn().get_variable_value("${OUTPUT DIR}")
        if robot_dir:
            return str(robot_dir)
    except Exception:
        pass  # Not running inside Robot context
    return ""


def _resolve_output_file() -> str:
    """Resolve the full path to Robot Framework's output XML file.

    Priority:
    1. ``ROBOT_OUTPUT_DIR`` env var + ``output.xml`` (backward compatible).
    2. Robot Framework's ``${OUTPUT FILE}`` built-in variable (respects
       ``--output`` flag and ``--output NONE``).
    3. Empty string if neither is available.
    """
    env_dir = os.getenv("ROBOT_OUTPUT_DIR")
    if env_dir:
        return os.path.join(env_dir, "output.xml")
    try:
        output_file = BuiltIn().get_variable_value("${OUTPUT FILE}")
        if output_file and str(output_file).upper() != "NONE":
            return str(output_file)
    except Exception:
        pass  # Not running inside Robot context
    return ""


def _read_and_compress_output_xml() -> bytes:
    """Read output.xml from Robot's output directory and gzip-compress it."""
    output_path = _resolve_output_file()
    if not output_path:
        return b""
    if not os.path.isfile(output_path):
        return b""
    try:
        with open(output_path, "rb") as f:
            return gzip.compress(f.read())
    except OSError:
        return b""


def _build_output_xml_source() -> str:
    """Return the filesystem path to the Robot Framework output.xml.

    This traces the test run back to the original output.xml that was
    produced by Robot Framework, enabling audit and replay.
    """
    output_path = _resolve_output_file()
    if output_path:
        if os.path.isfile(output_path):
            return os.path.abspath(output_path)
        return output_path
    return ""


def _build_output_xml_url() -> str:
    """Build a URL to the output.xml file from environment variables.

    Only returns proper web URLs. Returns empty string when no web URL
    is available (never stores filesystem paths).

    Priority:
    1. REPORT_BASE_URL — explicit base URL
    2. CI_JOB_URL — GitLab CI artifact URL pattern
    """
    base = os.getenv("REPORT_BASE_URL")
    if base:
        return f"{base.rstrip('/')}/output.xml"

    ci_job_url = os.getenv("CI_JOB_URL")
    if ci_job_url:
        return f"{ci_job_url}/artifacts/browse/output.xml"

    return ""


def _format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def _safe_int(value: Optional[str]) -> Optional[int]:
    """Convert a string to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _extract_llm_metrics(metrics_json: Optional[str]) -> Dict[str, Any]:
    """Extract individual metrics from the llm_metrics JSON string.

    Returns a dict with keys matching the Ollama metrics names.
    Missing or unparseable data returns an empty dict.
    """
    if not metrics_json:
        return {}
    try:
        data = json.loads(metrics_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return {
        "eval_count": data.get("eval_count"),
        "eval_duration_ns": data.get("eval_duration_ns"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "prompt_eval_duration_ns": data.get("prompt_eval_duration_ns"),
        "load_duration_ns": data.get("load_duration_ns"),
        "total_duration_ns": data.get("total_duration_ns"),
        "eval_rate": data.get("eval_rate"),
        "num_ctx": data.get("num_ctx"),
        "num_predict": data.get("num_predict"),
        # OpenAI token detail fields
        "reasoning_tokens": data.get("reasoning_tokens"),
        "cached_tokens": data.get("cached_tokens"),
        "accepted_prediction_tokens": data.get("accepted_prediction_tokens"),
        "rejected_prediction_tokens": data.get("rejected_prediction_tokens"),
    }


def _get_robot_float(var_name: str) -> float:
    """Get a float Robot variable, falling back to env var."""
    try:
        val = BuiltIn().get_variable_value(f"${{{var_name}}}")
        if val is not None:
            return float(val)
    except Exception:
        pass
    env_val = os.getenv(var_name)
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            pass
    return 0.0


def _get_robot_int(var_name: str) -> int:
    """Get an int Robot variable, falling back to env var."""
    try:
        val = BuiltIn().get_variable_value(f"${{{var_name}}}")
        if val is not None:
            return int(val)
    except Exception:
        pass
    env_val = os.getenv(var_name)
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            pass
    return 0
