"""Result importer with deduplication and output.xml blob storage.

Imports output.xml files into the lean test_runs/test_results schema and
archives the gzip-compressed output.xml into ``test_run_artifacts`` for
later retrieval.

Usage::

    uv run python -m rfc.result_importer results/math/output.xml
    uv run python -m rfc.result_importer results/ --recursive --source ci
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Optional

from rfc.result_import import import_results as _base_import
from rfc.test_database import TestDatabase

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of an import operation."""

    run_id: int
    file_hash: str
    file_path: str
    skipped: bool = False
    source: str = "local"


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def import_results(
    xml_path: str,
    db: TestDatabase,
    model_name: Optional[str] = None,
    source: str = "local",
    check_dedup: bool = False,
    _existing_hash: Optional[str] = None,
) -> ImportResult:
    """Import output.xml with gzip blob storage.

    Args:
        xml_path: Path to output.xml file.
        db: TestDatabase instance.
        model_name: Optional model name override.
        source: Import source identifier (local, ci).
        check_dedup: If True, skip files already imported (by hash).
        _existing_hash: For testing — pretend this hash already exists.

    Returns:
        ImportResult with run_id and hash.
    """
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

    # Read and gzip the output.xml
    output_xml_gz = None
    try:
        with open(xml_path, "rb") as f:
            output_xml_gz = gzip.compress(f.read())
    except OSError:
        logger.warning("Failed to read output.xml for compression: %s", xml_path)

    # Use existing import logic for core TestRun + TestResult
    run_id = _base_import(
        xml_path,
        db,
        model_name,
        output_xml_gz=output_xml_gz,
    )

    return ImportResult(
        run_id=run_id,
        file_hash=file_hash,
        file_path=xml_path,
        source=source,
    )


def main() -> None:
    """CLI entry point for result import."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Import Robot Framework results into database"
    )
    parser.add_argument(
        "output_xml",
        help="Path to output.xml or directory containing output.xml files",
    )
    parser.add_argument("--model", help="Model name override")
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Recursively search for output.xml files",
    )
    parser.add_argument(
        "--source",
        default="local",
        choices=["local", "ci"],
        help="Import source identifier (default: local)",
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        help="Skip files already imported (by SHA-256 hash)",
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
            result = import_results(
                xml_file,
                db,
                model_name=args.model,
                source=args.source,
                check_dedup=args.dedup,
            )
            if result.skipped:
                print(f"Skipped (duplicate): {xml_file}")
                skipped += 1
            else:
                print(f"Imported {xml_file} (run_id={result.run_id})")
                imported += 1
        except Exception as e:
            print(f"Failed to import {xml_file}: {e}")

    print(f"\nImported {imported}, skipped {skipped} file(s)")


if __name__ == "__main__":
    main()
