"""Tests for the extended result importer with dedup and keyword import.

Covers SHA-256 deduplication, keyword timing extraction from output.xml,
Ollama metrics import from sibling JSON, and source tracking.
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.rfc.result_importer import (
    ImportResult,
    compute_file_hash,
    import_results_extended,
    parse_keywords_from_xml,
)

# Reuse the minimal fixture from test_import_test_results
MINIMAL_OUTPUT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Math Tests" id="s1">
    <metadata>
      <item name="Model">llama3</item>
      <item name="Commit_SHA">abc123</item>
      <item name="Branch">main</item>
      <item name="Timestamp">2025-06-15T10:00:00</item>
    </metadata>
    <test name="IQ 100 Basic Addition" id="s1-t1">
      <doc>What is 2 + 2?</doc>
      <tags><tag>score:1</tag></tags>
      <kw name="Ask LLM" library="rfc.keywords">
        <msg>Answer: 4</msg>
        <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:02.000000"/>
      </kw>
      <kw name="Grade Answer" library="rfc.keywords">
        <msg>Expected: 4</msg>
        <status status="PASS" start="2025-06-15T10:00:02.000000" end="2025-06-15T10:00:02.500000"/>
      </kw>
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:03.000000"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="0">All Tests</stat></total>
  </statistics>
</robot>
"""

OLLAMA_TIMESTAMPS_JSON = json.dumps(
    [
        {
            "keyword": "Ask LLM",
            "model": "llama3",
            "endpoint": "http://localhost:11434",
            "start": "2025-06-15T10:00:01.000000",
            "end": "2025-06-15T10:00:02.000000",
            "duration_seconds": 1.0,
            "prompt": "What is 2 + 2?",
        }
    ]
)


class TestComputeFileHash:
    def test_returns_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "test.xml"
        f.write_text("hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert compute_file_hash(str(f)) == expected

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.xml"
        f2 = tmp_path / "b.xml"
        f1.write_text("alpha")
        f2.write_text("beta")
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))


class TestParseKeywordsFromXml:
    def test_extracts_keywords_with_library(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        keywords = parse_keywords_from_xml(str(xml_file))
        assert len(keywords) == 2
        assert keywords[0]["keyword_name"] == "Ask LLM"
        assert keywords[0]["library_name"] == "rfc.keywords"
        assert keywords[0]["test_name"] == "IQ 100 Basic Addition"
        assert keywords[0]["status"] == "PASS"

    def test_calculates_duration(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        keywords = parse_keywords_from_xml(str(xml_file))
        # Ask LLM: 10:00:01 -> 10:00:02 = 1 second
        assert keywords[0]["duration_seconds"] == pytest.approx(1.0, abs=0.1)

    def test_empty_xml_returns_empty(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(
            '<?xml version="1.0"?>'
            '<robot><suite name="X" id="s1">'
            '<status status="PASS"/></suite>'
            "<statistics><total>"
            '<stat pass="0" fail="0">All Tests</stat>'
            "</total></statistics></robot>"
        )
        keywords = parse_keywords_from_xml(str(xml_file))
        assert keywords == []


class TestImportResultsExtended:
    def _write_xml(self, tmp_path: Path) -> Path:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        return xml_file

    def _mock_db(self) -> MagicMock:
        db = MagicMock()
        db.db_path = ":memory:"
        db.add_test_run.return_value = 42
        return db

    def test_imports_and_returns_result(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        result = import_results_extended(str(xml_file), db)
        assert isinstance(result, ImportResult)
        assert result.run_id == 42
        assert result.file_hash is not None
        assert result.skipped is False

    def test_dedup_skips_duplicate(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        # First import
        result1 = import_results_extended(str(xml_file), db)
        # Simulate the hash existing in import_log
        db.execute_sql = MagicMock(return_value=[(1,)])
        result2 = import_results_extended(
            str(xml_file), db, check_dedup=True, _existing_hash=result1.file_hash
        )
        assert result2.skipped is True

    def test_source_tracking(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        result = import_results_extended(str(xml_file), db, source="ftp")
        assert result.source == "ftp"

    def test_keyword_results_added(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        import_results_extended(str(xml_file), db)
        # Should have called add_keyword_results with extracted keywords
        db.add_keyword_results.assert_called_once()
        kw_results = db.add_keyword_results.call_args[0][0]
        assert len(kw_results) == 2

    def test_ollama_metrics_imported_from_sibling(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        # Write sibling ollama_timestamps.json
        (tmp_path / "ollama_timestamps.json").write_text(OLLAMA_TIMESTAMPS_JSON)
        db = self._mock_db()
        result = import_results_extended(str(xml_file), db)
        assert result.ollama_metrics_count == 1
