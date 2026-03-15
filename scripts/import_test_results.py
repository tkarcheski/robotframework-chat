"""Import Robot Framework test results into the database.

Parses output.xml files (including combined rebot output) and inserts
test run data and individual results into the test history database.

Respects DATABASE_URL for PostgreSQL; defaults to SQLite.
"""

import argparse
import gzip
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
            tag_texts: list[str] = []
            for tag in test.findall("tags/tag"):
                if tag.text:
                    tag_texts.append(tag.text)
                    if tag.text.startswith("score:"):
                        try:
                            score = int(tag.text.split(":")[1])
                        except (ValueError, IndexError):
                            pass
            tags_str = ",".join(tag_texts) if tag_texts else None

            actual_answer = None
            expected_answer = None
            for msg in test.findall(".//msg"):
                text = msg.text or ""
                if text.startswith("RFC_DATA:actual_answer:"):
                    actual_answer = text[len("RFC_DATA:actual_answer:"):]
                elif text.startswith("RFC_DATA:expected_answer:"):
                    expected_answer = text[len("RFC_DATA:expected_answer:"):]
                elif text.startswith("RFC_DATA:grading_reason:"):
                    grading_reason = text[len("RFC_DATA:grading_reason:"):]
                elif text.startswith("RFC_DATA:score:"):
                    try:
                        score = int(text[len("RFC_DATA:score:"):])
                    except (ValueError, IndexError):
                        pass

            test_results.append(
                {
                    "name": test_name,
                    "status": test_status,
                    "score": score,
                    "tags": tags_str,
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
    xml_path: str,
    db: TestDatabase,
    model_name: Optional[str] = None,
    report_base_url: Optional[str] = None,
    output_xml_gz: Optional[bytes] = None,
    output_xml_url: Optional[str] = None,
) -> int:
    """Import a single output.xml file into database.

    Args:
        xml_path: Path to output.xml file
        db: TestDatabase instance
        model_name: Optional model name override
        report_base_url: Base URL for report links
        output_xml_gz: Pre-compressed output.xml blob (optional)
        output_xml_url: URL to output.xml (optional)

    Returns:
        Run ID of the inserted record
    """
    data = parse_output_xml(xml_path)
    metadata = data["metadata"]

    if model_name is None:
        model_name = (
            metadata.get("Default_Model")
            or metadata.get("Model")
            or metadata.get("Model_Name")
            or metadata.get("Selected_Model")
            or os.getenv("DEFAULT_MODEL", "unknown")
        )

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

    timestamp_str = metadata.get("Timestamp")
    if timestamp_str:
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.now()
    else:
        timestamp = datetime.now()

    # Build output_xml_url from report_base_url if not provided
    if output_xml_url is None and report_base_url:
        output_xml_url = f"{report_base_url.rstrip('/')}/output.xml"

    # Compress output.xml if not already provided
    if output_xml_gz is None:
        try:
            with open(xml_path, "rb") as f:
                output_xml_gz = gzip.compress(f.read())
        except OSError:
            pass

    run = TestRun(
        timestamp=timestamp,
        model_name=model_name or "unknown",
        test_suite=data["suite_name"],
        total_tests=data["total_tests"],
        passed=data["passed"],
        failed=data["failed"],
        skipped=data["skipped"],
        duration_seconds=data["duration"],
        git_commit=git_commit,
        git_branch=git_branch,
        hostname=os.getenv("HOSTNAME"),
        rfc_version=__version__,
        output_xml_url=output_xml_url,
        output_xml_gz=output_xml_gz,
        output_xml_source=os.path.abspath(xml_path),
    )

    run_id = db.add_test_run(run)

    test_results = [
        TestResult(
            run_id=run_id,
            test_name=td["name"],
            test_status=td["status"],
            score=td["score"],
            tags=td.get("tags"),
            question=td["question"],
            expected_answer=td["expected_answer"],
            actual_answer=td["actual_answer"],
            grading_reason=td["grading_reason"],
            rfc_version=__version__,
        )
        for td in data["test_results"]
    ]

    db.add_test_results(test_results)

    return run_id


def main() -> None:
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
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Recursively search for output.xml files in directory",
    )
    parser.add_argument(
        "--report-base-url",
        help="Base URL for output.xml web access",
    )

    args = parser.parse_args()

    db = TestDatabase()

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
            run_id = import_results(xml_file, db, args.model, args.report_base_url)
            print(f"Imported {xml_file} (run_id={run_id})")
            imported_count += 1
        except Exception as e:
            print(f"Failed to import {xml_file}: {e}")

    print(f"\nImported {imported_count} test run(s)")


if __name__ == "__main__":
    main()
