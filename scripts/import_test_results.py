"""Import Robot Framework test results into the database.

Parses output.xml files (including combined rebot output) and inserts
test run data and individual results into the test history database.

Respects DATABASE_URL for PostgreSQL; defaults to SQLite.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rfc import __version__
from rfc.test_database import TestDatabase, TestResult, TestRun


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


def parse_output_xml(xml_path: str) -> dict:
    """Parse Robot Framework output.xml file.

    Handles both single-suite output and combined rebot output
    (which nests sub-suites).

    Args:
        xml_path: Path to output.xml file

    Returns:
        Dictionary with parsed test data
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Get top-level suite info
    suite = root.find("suite")
    suite_name = suite.get("name") if suite is not None else "unknown"

    # Get statistics
    statistics = root.find("statistics")
    total_stats = statistics.find("total") if statistics is not None else None

    passed = failed = skipped = 0
    if total_stats is not None:
        for stat in total_stats.findall("stat"):
            passed += int(stat.get("pass", 0))
            failed += int(stat.get("fail", 0))
            skipped += int(stat.get("skip", 0))
    total_tests = passed + failed

    # Calculate duration from suite start/end times
    duration = 0.0
    status = suite.find("status") if suite is not None else None
    if status is not None:
        start_str = status.get("start", "") or status.get("starttime", "")
        end_str = status.get("end", "") or status.get("endtime", "")
        start_dt = _parse_rf_timestamp(start_str)
        end_dt = _parse_rf_timestamp(end_str)
        if start_dt and end_dt:
            duration = (end_dt - start_dt).total_seconds()

    # Extract metadata from suite (may be on top-level or nested)
    metadata: dict[str, str] = {}
    if suite is not None:
        for meta in suite.findall(".//metadata/item"):
            name = meta.get("name", "")
            value = meta.text or ""
            metadata[name] = value

    # Extract individual test results (recursive -- handles nested suites)
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
            grading_reason = None
            for tag in test.findall("tags/tag"):
                if tag.text and tag.text.startswith("score:"):
                    try:
                        score = int(tag.text.split(":")[1])
                    except (ValueError, IndexError):
                        pass

            actual_answer = None
            expected_answer = None
            for msg in test.findall(".//msg"):
                text = msg.text or ""
                if "Answer:" in text or "Response:" in text:
                    actual_answer = text
                if "Expected:" in text:
                    expected_answer = text

            test_results.append(
                {
                    "name": test_name,
                    "status": test_status,
                    "score": score,
                    "question": question,
                    "expected_answer": expected_answer,
                    "actual_answer": actual_answer,
                    "grading_reason": grading_reason,
                }
            )

    return {
        "suite_name": suite_name,
        "total_tests": total_tests,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration": duration,
        "metadata": metadata,
        "test_results": test_results,
    }


def import_results(
    xml_path: str, db: TestDatabase, model_name: Optional[str] = None
) -> int:
    """Import a single output.xml file into database.

    Args:
        xml_path: Path to output.xml file
        db: TestDatabase instance
        model_name: Optional model name override

    Returns:
        Run ID of the inserted record
    """
    data = parse_output_xml(xml_path)
    metadata = data["metadata"]

    if model_name is None:
        model_name = metadata.get("Model", os.getenv("DEFAULT_MODEL", "unknown"))

    model_release_date = metadata.get("Model_Release_Date")
    model_parameters = metadata.get("Model_Parameters")

    # Canonical keys first, then legacy GitLab-specific keys, then env vars
    git_commit = (
        metadata.get("Commit_SHA")
        or metadata.get("GitLab Commit")
        or os.getenv("CI_COMMIT_SHA")
        or os.getenv("GITHUB_SHA", "")
    )
    git_branch = (
        metadata.get("Branch")
        or metadata.get("GitLab Branch")
        or os.getenv("CI_COMMIT_REF_NAME")
        or os.getenv("GITHUB_REF_NAME", "")
    )
    pipeline_url = (
        metadata.get("Pipeline_URL")
        or metadata.get("GitLab Pipeline")
        or os.getenv("CI_PIPELINE_URL", "")
    )
    runner_id = (
        metadata.get("Runner_ID")
        or metadata.get("Runner ID")
        or os.getenv("CI_RUNNER_ID")
        or os.getenv("RUNNER_NAME", "")
    )
    runner_tags = (
        metadata.get("Runner_Tags")
        or metadata.get("Runner Tags")
        or os.getenv("CI_RUNNER_TAGS", "")
    )

    timestamp_str = metadata.get("Timestamp")
    if timestamp_str:
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.now()
    else:
        timestamp = datetime.now()

    run = TestRun(
        timestamp=timestamp,
        model_name=model_name or "unknown",
        model_release_date=model_release_date,
        model_parameters=model_parameters,
        test_suite=data["suite_name"],
        git_commit=git_commit,
        git_branch=git_branch,
        pipeline_url=pipeline_url,
        runner_id=runner_id,
        runner_tags=runner_tags,
        total_tests=data["total_tests"],
        passed=data["passed"],
        failed=data["failed"],
        skipped=data["skipped"],
        duration_seconds=data["duration"],
        rfc_version=__version__,
    )

    run_id = db.add_test_run(run)

    test_results = [
        TestResult(
            run_id=run_id,
            test_name=td["name"],
            test_status=td["status"],
            score=td["score"],
            question=td["question"],
            expected_answer=td["expected_answer"],
            actual_answer=td["actual_answer"],
            grading_reason=td["grading_reason"],
        )
        for td in data["test_results"]
    ]

    db.add_test_results(test_results)

    return run_id


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Import Robot Framework results into test database"
    )
    parser.add_argument(
        "output_xml",
        help="Path to output.xml file or directory containing output.xml files",
    )
    parser.add_argument(
        "--model",
        help="Model name override (default: from metadata or DEFAULT_MODEL env var)",
    )
    parser.add_argument("--db", help="Database path (default: data/test_history.db)")
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Recursively search for output.xml files in directory",
    )

    args = parser.parse_args()

    # Initialize database (respects DATABASE_URL env var for PostgreSQL)
    if args.db:
        db = TestDatabase(db_path=args.db)
    else:
        db = TestDatabase()

    # Find output.xml files
    xml_files: list[str] = []
    if os.path.isfile(args.output_xml):
        xml_files.append(args.output_xml)
    elif os.path.isdir(args.output_xml):
        if args.recursive:
            for root, _dirs, files in os.walk(args.output_xml):
                for f in files:
                    if f == "output.xml":
                        xml_files.append(os.path.join(root, f))
        else:
            xml_path = os.path.join(args.output_xml, "output.xml")
            if os.path.exists(xml_path):
                xml_files.append(xml_path)

    if not xml_files:
        print(f"No output.xml files found in: {args.output_xml}")
        sys.exit(1)

    imported_count = 0
    for xml_file in xml_files:
        try:
            run_id = import_results(xml_file, db, args.model)
            print(f"Imported {xml_file} (run_id={run_id})")
            imported_count += 1
        except Exception as e:
            print(f"Failed to import {xml_file}: {e}")

    print(f"\nImported {imported_count} test run(s) into database at {db.db_path}")


if __name__ == "__main__":
    main()
