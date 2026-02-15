"""Upload Robot Framework test artifacts to the PostgreSQL database.

Parses output.xml files from completed dashboard sessions and imports
them into the same PostgreSQL database that Superset reads from, making
test results immediately visible in Superset dashboards.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from rfc.test_database import TestDatabase, TestResult, TestRun

logger = logging.getLogger(__name__)


def _find_output_xml(session_dir: Path) -> Path | None:
    """Find the most recent output.xml in a session directory.

    Robot Framework with ``-T`` (timestamp) creates files like
    ``output-20240213-123456.xml``.  We prefer the plain ``output.xml``
    first, then fall back to the most recent timestamped variant.
    """
    plain = session_dir / "output.xml"
    if plain.exists():
        return plain

    # Timestamped variants
    candidates = sorted(session_dir.glob("output-*.xml"), reverse=True)
    return candidates[0] if candidates else None


def _parse_rf_timestamp(ts: str) -> Optional[datetime]:
    """Parse a Robot Framework timestamp.

    RF 7.x uses ISO-like format (2024-02-13T12:34:56.789000).
    Older versions use 20240213 12:34:56.789.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        pass
    try:
        return datetime.strptime(ts.split(".")[0], "%Y%m%d %H:%M:%S")
    except ValueError:
        return None


def _import_output_xml(xml_path: str, db: TestDatabase) -> int:
    """Parse and import a single output.xml file into the database.

    This mirrors the logic in ``scripts/import_test_results.py`` so the
    dashboard can upload results without depending on that script as an
    importable module.

    Returns:
        The run_id of the inserted record.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    suite = root.find("suite")
    suite_name = suite.get("name") if suite is not None else "unknown"

    # Statistics
    statistics = root.find("statistics")
    total_stats = statistics.find("total") if statistics is not None else None

    passed = failed = skipped = 0
    if total_stats is not None:
        for stat in total_stats.findall("stat"):
            passed += int(stat.get("pass", 0))
            failed += int(stat.get("fail", 0))
            skipped += int(stat.get("skip", 0))
    total_tests = passed + failed

    # Duration
    duration = 0.0
    status_elem = suite.find("status") if suite is not None else None
    if status_elem is not None:
        start_str = status_elem.get("start", "") or status_elem.get("starttime", "")
        end_str = status_elem.get("end", "") or status_elem.get("endtime", "")
        start_dt = _parse_rf_timestamp(start_str)
        end_dt = _parse_rf_timestamp(end_str)
        if start_dt and end_dt:
            duration = (end_dt - start_dt).total_seconds()

    # Metadata
    metadata: dict[str, str] = {}
    if suite is not None:
        for meta in suite.findall(".//metadata/item"):
            name = meta.get("name", "")
            value = meta.text or ""
            metadata[name] = value

    model_name = metadata.get("Model", os.getenv("DEFAULT_MODEL", "unknown"))
    timestamp_str = metadata.get("Timestamp")
    if timestamp_str:
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.now()
    else:
        timestamp = datetime.now()

    try:
        from rfc import __version__

        rfc_version = __version__
    except ImportError:
        rfc_version = None

    run = TestRun(
        timestamp=timestamp,
        model_name=model_name,
        model_release_date=metadata.get("Model_Release_Date"),
        model_parameters=metadata.get("Model_Parameters"),
        test_suite=suite_name or "unknown",
        gitlab_commit=metadata.get("GitLab Commit", os.getenv("CI_COMMIT_SHA", "")),
        gitlab_branch=metadata.get(
            "GitLab Branch", os.getenv("CI_COMMIT_REF_NAME", "")
        ),
        gitlab_pipeline_url=metadata.get(
            "GitLab Pipeline", os.getenv("CI_PIPELINE_URL", "")
        ),
        runner_id=metadata.get("Runner ID", os.getenv("CI_RUNNER_ID", "")),
        runner_tags=metadata.get("Runner Tags", os.getenv("CI_RUNNER_TAGS", "")),
        total_tests=total_tests,
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_seconds=duration,
        rfc_version=rfc_version,
    )

    run_id = db.add_test_run(run)

    # Individual test results
    test_results = []
    if suite is not None:
        for test in suite.findall(".//test"):
            test_name = test.get("name", "unknown")
            test_status_elem = test.find("status")
            test_status = (
                test_status_elem.get("status", "UNKNOWN")
                if test_status_elem is not None
                else "UNKNOWN"
            )

            doc = test.find("doc")
            question = doc.text if doc is not None else None

            score = None
            for tag in test.findall("tags/tag"):
                if tag.text and tag.text.startswith("score:"):
                    try:
                        score = int(tag.text.split(":")[1])
                    except (ValueError, IndexError):
                        pass

            actual_answer = None
            expected_answer = None
            for msg in test.findall(".//msg"):
                msg_text = msg.text or ""
                if "Answer:" in msg_text or "Response:" in msg_text:
                    actual_answer = msg_text
                if "Expected:" in msg_text:
                    expected_answer = msg_text

            test_results.append(
                TestResult(
                    run_id=run_id,
                    test_name=test_name,
                    test_status=test_status,
                    score=score,
                    question=question,
                    expected_answer=expected_answer,
                    actual_answer=actual_answer,
                    grading_reason=None,
                )
            )

    db.add_test_results(test_results)
    return run_id


def upload_session_results(
    session_id: str,
    output_dir: str = "results/dashboard",
    database_url: str | None = None,
) -> dict:
    """Upload test results from a dashboard session to the database.

    Args:
        session_id: The session UUID prefix (e.g. ``"a1b2c3d4"``).
        output_dir: Base directory where session results are stored.
        database_url: Database connection URL.  Falls back to the
            ``DATABASE_URL`` environment variable, then SQLite default.

    Returns:
        A dict with upload status information::

            {"status": "success", "run_id": 42, "file": "output.xml", ...}
            {"status": "error", "message": "..."}
    """
    session_dir = Path(output_dir) / session_id

    if not session_dir.exists():
        return {
            "status": "error",
            "message": f"Session directory not found: {session_dir}",
        }

    xml_path = _find_output_xml(session_dir)
    if xml_path is None:
        return {
            "status": "error",
            "message": f"No output.xml found in {session_dir}",
        }

    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        return {
            "status": "error",
            "message": (
                "DATABASE_URL is not configured. "
                "Set it to a PostgreSQL connection string to enable uploads."
            ),
        }

    try:
        db = TestDatabase(database_url=url)
        run_id = _import_output_xml(str(xml_path), db)

        logger.info(
            "Uploaded session %s results (run_id=%d) from %s",
            session_id,
            run_id,
            xml_path,
        )

        return {
            "status": "success",
            "run_id": run_id,
            "file": str(xml_path),
            "session_id": session_id,
        }

    except Exception as e:
        logger.exception("Failed to upload session %s results", session_id)
        return {
            "status": "error",
            "message": f"Upload failed: {e}",
        }
