"""Tests for the result importer with dedup and output.xml blob storage.

Covers SHA-256 deduplication and core import flow for the 2-table schema.
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock


from src.rfc.result_importer import (
    ImportResult,
    compute_file_hash,
    import_results,
)


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
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:03.000000"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="0">All Tests</stat></total>
  </statistics>
</robot>
"""


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


class TestImportResults:
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
        result = import_results(str(xml_file), db)
        assert isinstance(result, ImportResult)
        assert result.run_id == 42
        assert result.file_hash is not None
        assert result.skipped is False

    def test_dedup_skips_duplicate(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        result1 = import_results(str(xml_file), db)
        result2 = import_results(
            str(xml_file), db, check_dedup=True, _existing_hash=result1.file_hash
        )
        assert result2.skipped is True

    def test_source_tracking(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        result = import_results(str(xml_file), db, source="ci")
        assert result.source == "ci"
