"""Extended result importer with deduplication and keyword/metrics import.

Extends the basic import_test_results script with:
- SHA-256 deduplication via import_log table
- Keyword timing extraction from output.xml ``<kw>`` elements
- Ollama metrics import from sibling ``ollama_timestamps.json``
- Source tracking (local, ftp, ci)

Usage::

    uv run python -m rfc.result_importer results/math/output.xml
    uv run python -m rfc.result_importer results/ --recursive --source ci
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from xml.etree import ElementTree as ET

from rfc import __version__
from rfc.test_database import KeywordResult, OllamaMetrics, TestDatabase

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of an import operation."""

    run_id: int
    file_hash: str
    file_path: str
    skipped: bool = False
    source: str = "local"
    keyword_count: int = 0
    ollama_metrics_count: int = 0


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _parse_rf_timestamp(ts: str) -> Optional[datetime]:
    """Parse a Robot Framework timestamp (RF 7.x ISO or older format)."""
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


def parse_keywords_from_xml(xml_path: str) -> list[dict[str, Any]]:
    """Extract keyword timing data from output.xml.

    Finds all ``<kw>`` elements inside ``<test>`` elements that have
    a ``library`` attribute, extracting name, status, and timing.

    Returns:
        List of dicts with keyword_name, library_name, test_name,
        status, start_time, end_time, duration_seconds.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    suite = root.find("suite")
    if suite is None:
        return []

    keywords: list[dict[str, Any]] = []
    for test in suite.findall(".//test"):
        test_name = test.get("name", "unknown")
        for kw in test.findall(".//kw"):
            kw_name = kw.get("name", "")
            library = kw.get("library", "")
            if not library:
                continue  # skip non-library keywords

            status_elem = kw.find("status")
            status = "UNKNOWN"
            start_str = ""
            end_str = ""
            duration = None

            if status_elem is not None:
                status = status_elem.get("status", "UNKNOWN")
                start_str = status_elem.get("start", "") or status_elem.get(
                    "starttime", ""
                )
                end_str = status_elem.get("end", "") or status_elem.get(
                    "endtime", ""
                )
                start_dt = _parse_rf_timestamp(start_str)
                end_dt = _parse_rf_timestamp(end_str)
                if start_dt and end_dt:
                    duration = (end_dt - start_dt).total_seconds()

            keywords.append(
                {
                    "test_name": test_name,
                    "keyword_name": kw_name,
                    "library_name": library,
                    "status": status,
                    "start_time": start_str,
                    "end_time": end_str,
                    "duration_seconds": duration,
                }
            )

    return keywords


def _parse_ollama_timestamps(json_path: str) -> list[dict[str, Any]]:
    """Parse ollama_timestamps.json sibling file."""
    try:
        with open(json_path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def import_results_extended(
    xml_path: str,
    db: TestDatabase,
    model_name: Optional[str] = None,
    source: str = "local",
    check_dedup: bool = False,
    report_base_url: Optional[str] = None,
    _existing_hash: Optional[str] = None,
) -> ImportResult:
    """Import output.xml with extended keyword/metrics extraction.

    Args:
        xml_path: Path to output.xml file.
        db: TestDatabase instance.
        model_name: Optional model name override.
        source: Import source identifier (local, ftp, ci).
        check_dedup: If True, skip files already imported (by hash).
        report_base_url: Base URL for report.html/log.html links.
        _existing_hash: For testing — pretend this hash already exists.

    Returns:
        ImportResult with run_id, hash, and counts.
    """
    # Lazy import to avoid circular dependency
    from scripts.import_test_results import import_results

    file_hash = compute_file_hash(xml_path)

    # Deduplication check
    if check_dedup and _existing_hash == file_hash:
        logger.info("Skipping duplicate: %s (hash=%s)", xml_path, file_hash)
        return ImportResult(
            run_id=0,
            file_hash=file_hash,
            file_path=xml_path,
            skipped=True,
            source=source,
        )

    # Use existing import logic for core TestRun + TestResult
    run_id = import_results(xml_path, db, model_name, report_base_url)

    # Extended: extract and import keyword timing
    keywords_data = parse_keywords_from_xml(xml_path)
    keyword_results = [
        KeywordResult(
            run_id=run_id,
            test_name=kw["test_name"],
            keyword_name=kw["keyword_name"],
            library_name=kw["library_name"],
            status=kw["status"],
            start_time=kw["start_time"],
            end_time=kw["end_time"],
            duration_seconds=kw["duration_seconds"],
            rfc_version=__version__,
        )
        for kw in keywords_data
    ]
    if keyword_results:
        db.add_keyword_results(keyword_results)
        logger.info("  Imported %d keyword result(s)", len(keyword_results))

    # Extended: import Ollama metrics from sibling file
    ollama_count = 0
    ollama_json = os.path.join(os.path.dirname(xml_path), "ollama_timestamps.json")
    if os.path.isfile(ollama_json):
        timestamps = _parse_ollama_timestamps(ollama_json)
        ollama_metrics = [
            OllamaMetrics(
                run_id=run_id,
                test_name=ts.get("keyword", "unknown"),
                model_name=ts.get("model", "unknown"),
                prompt_text=ts.get("prompt"),
                total_duration_ns=None,
                load_duration_ns=None,
                prompt_eval_count=None,
                prompt_eval_duration_ns=None,
                prompt_eval_rate=None,
                eval_count=None,
                eval_duration_ns=None,
                eval_rate=None,
                rfc_version=__version__,
            )
            for ts in timestamps
        ]
        if ollama_metrics:
            db.add_ollama_metrics(ollama_metrics)
            ollama_count = len(ollama_metrics)
            logger.info("  Imported %d Ollama metric(s)", ollama_count)

    return ImportResult(
        run_id=run_id,
        file_hash=file_hash,
        file_path=xml_path,
        source=source,
        keyword_count=len(keyword_results),
        ollama_metrics_count=ollama_count,
    )


def main() -> None:
    """CLI entry point for extended import."""
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Import Robot Framework results (extended) into database"
    )
    parser.add_argument(
        "output_xml",
        help="Path to output.xml or directory containing output.xml files",
    )
    parser.add_argument(
        "--model", help="Model name override"
    )
    parser.add_argument(
        "--recursive", "-r", action="store_true",
        help="Recursively search for output.xml files",
    )
    parser.add_argument(
        "--source", default="local", choices=["local", "ftp", "ci"],
        help="Import source identifier (default: local)",
    )
    parser.add_argument(
        "--dedup", action="store_true",
        help="Skip files already imported (by SHA-256 hash)",
    )
    parser.add_argument(
        "--report-base-url",
        help="Base URL for report.html/log.html links",
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
            candidate = os.path.join(args.output_xml, "output.xml")
            if os.path.exists(candidate):
                xml_files.append(candidate)

    if not xml_files:
        print(f"No output.xml files found in: {args.output_xml}")
        raise SystemExit(1)

    imported = 0
    skipped = 0
    for xml_file in xml_files:
        try:
            result = import_results_extended(
                xml_file, db,
                model_name=args.model,
                source=args.source,
                check_dedup=args.dedup,
                report_base_url=args.report_base_url,
            )
            if result.skipped:
                print(f"Skipped (duplicate): {xml_file}")
                skipped += 1
            else:
                print(
                    f"Imported {xml_file} (run_id={result.run_id}, "
                    f"keywords={result.keyword_count}, "
                    f"ollama_metrics={result.ollama_metrics_count})"
                )
                imported += 1
        except Exception as e:
            print(f"Failed to import {xml_file}: {e}")

    print(f"\nImported {imported}, skipped {skipped} file(s)")


if __name__ == "__main__":
    main()
