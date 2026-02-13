"""Import Robot Framework test results into SQLite database.

Parses output.xml files and inserts test run data and individual
results into the test history database.
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

from rfc.test_database import TestDatabase, TestResult, TestRun


def parse_output_xml(xml_path: str) -> dict:
    """Parse Robot Framework output.xml file.

    Args:
        xml_path: Path to output.xml file

    Returns:
        Dictionary with parsed test data
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Get suite info
    suite = root.find("suite")
    suite_name = suite.get("name") if suite is not None else "unknown"

    # Get statistics
    statistics = root.find("statistics")
    total_stats = statistics.find("total") if statistics is not None else None
    stat = total_stats.find("stat") if total_stats is not None else None

    if stat is not None:
        total_tests = int(stat.get("pass", 0)) + int(stat.get("fail", 0))
        passed = int(stat.get("pass", 0))
        failed = int(stat.get("fail", 0))
        skipped = int(stat.get("skip", 0))
    else:
        total_tests = passed = failed = skipped = 0

    # Calculate duration from suite start/end times
    status = suite.find("status") if suite is not None else None
    if status is not None:
        start_time = status.get("starttime", "")
        end_time = status.get("endtime", "")
        if start_time and end_time:
            try:
                # Parse format: 20240213 12:34:56.789
                start = datetime.strptime(start_time.split(".")[0], "%Y%m%d %H:%M:%S")
                end = datetime.strptime(end_time.split(".")[0], "%Y%m%d %H:%M:%S")
                duration = (end - start).total_seconds()
            except ValueError:
                duration = 0.0
        else:
            duration = 0.0
    else:
        duration = 0.0

    # Extract metadata from suite
    metadata = {}
    if suite is not None:
        for meta in suite.findall("metadata/item"):
            name = meta.get("name", "")
            value = meta.text or ""
            metadata[name] = value

    # Extract individual test results
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

            # Try to extract question/answer from test doc or messages
            doc = test.find("doc")
            question = doc.text if doc is not None else None

            # Look for score in test tags or messages
            score = None
            grading_reason = None
            for tag in test.findall("tags/tag"):
                if tag.text and tag.text.startswith("score:"):
                    try:
                        score = int(tag.text.split(":")[1])
                    except (ValueError, IndexError):
                        pass

            # Get actual answer from last message
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

    # Determine model name from metadata or parameter
    if model_name is None:
        model_name = metadata.get("Model", os.getenv("DEFAULT_MODEL", "unknown"))

    # Get model info from metadata
    model_release_date = metadata.get("Model_Release_Date")
    model_parameters = metadata.get("Model_Parameters")

    # Get CI info from metadata or environment
    gitlab_commit = metadata.get("GitLab Commit", os.getenv("CI_COMMIT_SHA", ""))
    gitlab_branch = metadata.get("GitLab Branch", os.getenv("CI_COMMIT_REF_NAME", ""))
    gitlab_pipeline = metadata.get("GitLab Pipeline", os.getenv("CI_PIPELINE_URL", ""))
    runner_id = metadata.get("Runner ID", os.getenv("CI_RUNNER_ID", ""))
    runner_tags = metadata.get("Runner Tags", os.getenv("CI_RUNNER_TAGS", ""))

    # Parse timestamp from metadata or use now
    timestamp_str = metadata.get("Timestamp")
    if timestamp_str:
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.now()
    else:
        timestamp = datetime.now()

    # Create test run
    run = TestRun(
        timestamp=timestamp,
        model_name=model_name or "unknown",
        model_release_date=model_release_date,
        model_parameters=model_parameters,
        test_suite=data["suite_name"],
        gitlab_commit=gitlab_commit,
        gitlab_branch=gitlab_branch,
        gitlab_pipeline_url=gitlab_pipeline,
        runner_id=runner_id,
        runner_tags=runner_tags,
        total_tests=data["total_tests"],
        passed=data["passed"],
        failed=data["failed"],
        skipped=data["skipped"],
        duration_seconds=data["duration"],
    )

    # Insert test run
    run_id = db.add_test_run(run)

    # Insert individual test results
    test_results = []
    for test_data in data["test_results"]:
        test_results.append(
            TestResult(
                run_id=run_id,
                test_name=test_data["name"],
                test_status=test_data["status"],
                score=test_data["score"],
                question=test_data["question"],
                expected_answer=test_data["expected_answer"],
                actual_answer=test_data["actual_answer"],
                grading_reason=test_data["grading_reason"],
            )
        )

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

    # Initialize database
    db = TestDatabase(args.db)

    # Find output.xml files
    xml_files = []
    if os.path.isfile(args.output_xml):
        xml_files.append(args.output_xml)
    elif os.path.isdir(args.output_xml):
        if args.recursive:
            for root, dirs, files in os.walk(args.output_xml):
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

    # Import each file
    imported_count = 0
    for xml_file in xml_files:
        try:
            run_id = import_results(xml_file, db, args.model)
            print(f"✓ Imported {xml_file} (Run ID: {run_id})")
            imported_count += 1
        except Exception as e:
            print(f"✗ Failed to import {xml_file}: {e}")

    print(f"\nImported {imported_count} test run(s) into database")


if __name__ == "__main__":
    main()
